"""Phase 4: the forecast-aware model bundle (models/model_bundle.py) and the feature-engineering
pieces adapted from xgboost-pred that feed it (replay_snapshot.py, county_storm_features.py,
oni_by_date.py). Needs no GCS/HURRICANE_MODEL_RUN -- the bundle artifact is local."""

import os
from datetime import datetime

import pytest

from models.county_storm_features import compute_county_storm_features
from models.model_bundle import ModelBundleUnavailable, apply_calibration, load_bundle
from models.oni_by_date import oni_anomaly_for_date
from models.replay_snapshot import snapshot_from_replay
from models.schema import FEATURE_COLUMNS, CountyFeatures

BUNDLE_NAME = "outage_xgb_real_v1"


@pytest.fixture(scope="module")
def bundle():
    return load_bundle(BUNDLE_NAME)


def test_bundle_loads_with_matching_metadata_and_calibration(bundle):
    assert bundle.model.is_fitted
    assert bundle.meta["feature_columns"] == FEATURE_COLUMNS
    assert bundle.calibration["base_model_artifact"] == f"{BUNDLE_NAME}.joblib"
    assert bundle.model_version == bundle.meta["model_version"]


def test_bad_bundle_name_fails_gracefully_not_a_crash():
    with pytest.raises(ModelBundleUnavailable):
        load_bundle("does_not_exist_v99")


def test_feature_schema_order_matches_the_trained_artifact():
    assert FEATURE_COLUMNS == [
        "max_wind_kt", "gust_wind_kt", "dist_to_track_nm", "forward_speed_kt", "quadrant_right",
        "population_log", "customers_served_log", "tree_canopy_pct", "nri_risk_score",
        "nri_eal_building_log", "svi_overall", "oni_anomaly", "lead_time_h",
    ]


def _county_features(**overrides) -> CountyFeatures:
    base = dict(fips="12086", name="Miami-Dade County", state="FL", max_wind_kt=89.4, dist_to_track_nm=54.2,
               forward_speed_kt=8.3, quadrant_right=1, population=2700000, customers_served=1300000,
               tree_canopy_pct=20.0, nri_risk_score=80.0, nri_eal_building=5e9, svi_overall=0.6,
               oni_anomaly=-0.23, lead_time_h=47.0)
    base.update(overrides)
    return CountyFeatures(**base)


def test_predict_one_returns_a_valid_calibrated_range(bundle):
    out = bundle.predict_one(_county_features())
    q = out["pct_customers_out"]
    assert 0.0 <= q["low"] <= q["median"] <= q["high"] <= 100.0
    assert out["risk_tier"] in ("green", "yellow", "orange", "red")
    assert out["model_bundle"] == BUNDLE_NAME
    assert out["calibration"]["status"] in ("stratified_conformal", "stratified_conformal_global_fallback")


def test_risk_tier_is_produced_consistently_for_the_same_inputs(bundle):
    cf = _county_features(fips="12071", name="Lee County")
    a, b = bundle.predict_one(cf), bundle.predict_one(cf)
    assert a["risk_tier"] == b["risk_tier"]
    assert a["pct_customers_out"] == b["pct_customers_out"]


def test_apply_calibration_keeps_low_median_high_ordered():
    calibration = {"pred_bands": [{"label": "0-5%", "lo": 0.0, "hi": 5.0}, {"label": "5-20%", "lo": 5.0, "hi": 20.0}],
                   "Q_global": 1.0, "Q_by_band": {"0-5%": 0.0}}
    cal = apply_calibration(2.0, 3.0, 4.0, calibration)
    assert cal.low <= cal.median <= cal.high


def test_oni_by_date_resolves_the_requested_historical_season():
    path = "data/raw/oni/oni.ascii.txt"
    if not os.path.exists(path):
        pytest.skip("oni.ascii.txt not cached locally")
    text = open(path).read()
    anomaly, season, year = oni_anomaly_for_date(text, datetime(2024, 7, 6))
    assert (season, year) == ("JJA", 2024)  # July's 3-month season is Jun-Jul-Aug
    assert anomaly is not None


def test_oni_by_date_returns_none_without_substituting_a_value():
    anomaly, season, year = oni_anomaly_for_date("", datetime(2024, 7, 6))
    assert anomaly is None and (season, year) == ("JJA", 2024)


def test_snapshot_from_replay_resolves_all_dynamic_features_via_adjacent_point():
    replay = {
        "storm_id": "AL022024", "storm_name": "Beryl", "advisory_init_utc": "2024-07-06T12:00:00+00:00",
        "closest_approach_utc": "2024-07-08T15:00:00+00:00", "lead_time_h": 51.0,
        "forecast": [
            {"tau_h": 0, "valid_utc": "2024-07-06T12:00:00+00:00", "lat": 20.0, "lon": -85.0, "vmax_kt": 90.0},
            {"tau_h": 24, "valid_utc": "2024-07-07T12:00:00+00:00", "lat": 24.0, "lon": -92.0, "vmax_kt": 70.0},
            {"tau_h": 51, "valid_utc": "2024-07-08T15:00:00+00:00", "lat": 29.5, "lon": -95.0, "vmax_kt": 50.0},
        ],
    }
    snapshot, adjacent = snapshot_from_replay(replay)
    assert snapshot.lead_time_h == 51.0
    assert adjacent is not None

    sf = compute_county_storm_features(29.76, -95.37, snapshot, adjacent_point=adjacent)
    assert sf.max_wind_kt > 0
    assert sf.dist_to_track_nm >= 0
    assert sf.forward_speed_kt is not None
    assert sf.forward_speed_source == "derived_from_adjacent_positions"
    assert sf.quadrant_right in (0, 1)
    assert sf.lead_time_h == 51.0


def test_snapshot_from_replay_with_a_single_point_has_no_adjacent():
    replay = {
        "storm_id": "AL022024", "storm_name": "Beryl", "advisory_init_utc": "2024-07-06T12:00:00+00:00",
        "closest_approach_utc": "2024-07-08T15:00:00+00:00", "lead_time_h": 51.0,
        "forecast": [{"tau_h": 51, "valid_utc": "2024-07-08T15:00:00+00:00", "lat": 29.5, "lon": -95.0, "vmax_kt": 50.0}],
    }
    snapshot, adjacent = snapshot_from_replay(replay)
    assert adjacent is None
    sf = compute_county_storm_features(29.76, -95.37, snapshot, adjacent_point=None)
    assert sf.forward_speed_kt is None and sf.forward_speed_source == "missing"
    assert sf.quadrant_right is None  # no heading resolvable from one point
