"""Tests for Phase 3Q: live feature construction, post-hoc calibration
application, and the real-model inference pipeline.

Synthetic ForecastSnapshot + NRI/SVI/ONI/MCC frames only, mirroring
test_training_row.py's fixture style -- no real GCS/shapefile dependency,
except for the two tests that explicitly check the real artifacts on disk
(local files only, fast, no network).
"""

from __future__ import annotations

import io
import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.agent.contracts import Impact
from backend.models import pipeline
from backend.models.atcf_forecast import ForecastPoint, ForecastSnapshot, WindRadii
from backend.models.live_inference import (
    LiveFeatureRow,
    UnresolvedLiveFeatureError,
    apply_calibration,
    build_live_feature_row,
    latest_published_oni,
    select_predicted_band,
)
from backend.models.outage_model import QuantileOutageModel
from backend.models.outage_target import load_mcc_customers
from backend.models.schema import FEATURE_COLUMNS

STORM_LAT, STORM_LON = 25.0, -85.0
VMAX = 100.0
RADII = {
    64: WindRadii("NEQ", ne_nm=30.0, se_nm=30.0, sw_nm=25.0, nw_nm=25.0),
    50: WindRadii("NEQ", ne_nm=60.0, se_nm=60.0, sw_nm=50.0, nw_nm=50.0),
    34: WindRadii("NEQ", ne_nm=120.0, se_nm=120.0, sw_nm=100.0, nw_nm=100.0),
}
COUNTY_FIPS = "12075"
COUNTY_LAT, COUNTY_LON = STORM_LAT + 10.0 / 60.0, STORM_LON  # ~10nm due north

NRI_DF = pd.DataFrame([{"fips": COUNTY_FIPS, "POPULATION": 40000, "HRCN_EALB": 500000.0, "HRCN_RISKS": 25.0}])
SVI_DF = pd.DataFrame([{"fips": COUNTY_FIPS, "RPL_THEMES": 0.65}])
MCC_SAMPLE = f"County_FIPS,Customers\n{COUNTY_FIPS},1000\n"
ONI_DF = pd.DataFrame([{"season": "JAS", "year": 2026, "anom": 0.6}])  # JAS middle month = Aug


def _snapshot(*, dir_deg=0.0, speed_kt=10.0, tau_h=72, lead_time_h=72,
              valid_time: datetime | None = None) -> ForecastSnapshot:
    cycle = datetime(2026, 8, 4, 18)  # cycle + 72h tau lands in August -> JAS season
    point = ForecastPoint(
        storm_id="AL992026", basin="AL", cyclone_num=99, tech="OFCL",
        cycle_init_time_utc=cycle, tau_h=tau_h, valid_time_utc=cycle + timedelta(hours=tau_h),
        lat=STORM_LAT, lon=STORM_LON, vmax_kt=VMAX, mslp_mb=950.0, storm_type="HU",
        dir_deg=dir_deg, speed_kt=speed_kt, storm_name="ALPHA", wind_radii=dict(RADII),
    )
    return ForecastSnapshot(
        lead_time_h=lead_time_h, forecast_tau_h=tau_h, cycle_init_time_utc=cycle,
        valid_time_utc=valid_time or point.valid_time_utc, forecast=point,
    )


def _build_row(**overrides) -> LiveFeatureRow:
    snapshot = overrides.pop("snapshot", _snapshot())
    mcc_df = overrides.pop("mcc_df", load_mcc_customers(io.StringIO(MCC_SAMPLE)))
    nri_df = overrides.pop("nri_df", NRI_DF)
    svi_df = overrides.pop("svi_df", SVI_DF)
    oni_df = overrides.pop("oni_df", ONI_DF)
    return build_live_feature_row(
        storm_id="AL992026", storm_name="ALPHA", county_fips=COUNTY_FIPS,
        county_lat=COUNTY_LAT, county_lon=COUNTY_LON, snapshot=snapshot,
        nri_df=nri_df, svi_df=svi_df, mcc_df=mcc_df, oni_df=oni_df,
        **overrides,
    )


# --- feature schema/order -----------------------------------------------------


def test_feature_dict_has_exactly_the_13_feature_columns():
    row = _build_row()
    assert set(row.to_feature_dict().keys()) == set(FEATURE_COLUMNS)
    assert len(row.to_feature_dict()) == 13


def test_feature_series_matches_feature_columns_order():
    row = _build_row()
    series = row.to_feature_series()
    assert list(series.index) == FEATURE_COLUMNS
    df = pd.DataFrame([series])
    assert list(df[FEATURE_COLUMNS].columns) == FEATURE_COLUMNS
    assert not df[FEATURE_COLUMNS].isnull().any().any()


def test_no_target_or_provenance_leaks_into_feature_view():
    row = _build_row()
    feature_keys = set(row.to_feature_dict().keys())
    for field in ("storm_id", "county_fips", "cycle_init_time_utc", "forecast_tau_h"):
        assert field not in feature_keys


# --- no double log transform (same contract as training_row.py) -------------


def test_population_and_customers_log_transformed_exactly_once():
    row = _build_row()
    assert row.population_log == pytest.approx(math.log1p(40000))
    assert row.customers_served_log == pytest.approx(math.log1p(1000.0))
    assert row.nri_risk_score == 25.0  # not logged
    assert row.svi_overall == 0.65  # not logged


# --- live "when" anchor: forecast's own valid_time, no impact_time_utc ------


def test_build_live_feature_row_needs_no_impact_time_utc():
    # the whole point of Phase 3Q's live snapshot definition: there is no
    # impact_time_utc parameter at all, unlike build_training_row()
    import inspect
    params = inspect.signature(build_live_feature_row).parameters
    assert "impact_time_utc" not in params


def test_oni_resolved_against_forecast_valid_time_not_a_future_truth():
    # cycle 2026-08-04T18 + tau 72h = 2026-08-07T18 -> August -> JAS season
    row = _build_row()
    assert row.oni_anomaly == 0.6


# --- unresolved required feature: raise, never fabricate --------------------


def test_missing_dir_raises_unresolved_live_feature_error():
    with pytest.raises(UnresolvedLiveFeatureError) as exc_info:
        _build_row(snapshot=_snapshot(dir_deg=None))
    assert "quadrant_right" in exc_info.value.missing_features


def test_missing_speed_no_adjacent_point_raises():
    with pytest.raises(UnresolvedLiveFeatureError) as exc_info:
        _build_row(snapshot=_snapshot(speed_kt=None))
    assert "forward_speed_kt" in exc_info.value.missing_features


def test_missing_nri_row_raises():
    empty_nri = pd.DataFrame(columns=["fips", "POPULATION", "HRCN_EALB", "HRCN_RISKS"])
    with pytest.raises(UnresolvedLiveFeatureError) as exc_info:
        _build_row(nri_df=empty_nri)
    missing = set(exc_info.value.missing_features)
    assert {"population_log", "nri_risk_score", "nri_eal_building_log"} <= missing


def test_missing_svi_row_raises():
    empty_svi = pd.DataFrame(columns=["fips", "RPL_THEMES"])
    with pytest.raises(UnresolvedLiveFeatureError) as exc_info:
        _build_row(svi_df=empty_svi)
    assert "svi_overall" in exc_info.value.missing_features


def test_missing_oni_season_raises():
    empty_oni = pd.DataFrame(columns=["season", "year", "anom"])
    with pytest.raises(UnresolvedLiveFeatureError) as exc_info:
        _build_row(oni_df=empty_oni)
    assert "oni_anomaly" in exc_info.value.missing_features


# --- Phase 3U: ONI publication-lag proxy (live/scenario inference only) ------
# NOAA's latest published season structurally lags the calendar (ONI is a
# 3-month running mean). A requested season strictly AFTER the latest one
# present in oni_df gets the latest published anomaly as an explicitly
# flagged proxy; an interior gap (requested season before/within already-
# published history but itself missing) must NOT be proxied.

MULTI_SEASON_ONI_DF = pd.DataFrame([
    {"season": "MJJ", "year": 2026, "anom": 0.9},
    {"season": "JJA", "year": 2026, "anom": 1.2},
    {"season": "JAS", "year": 2026, "anom": 2.16},  # latest officially published
])


def test_oni_exact_published_season_used_without_proxy():
    # Aug 2026 -> JAS, present exactly -- no proxy involved.
    row = _build_row(oni_df=MULTI_SEASON_ONI_DF, snapshot=_snapshot(valid_time=datetime(2026, 8, 15)))
    assert row.oni_anomaly == 2.16
    assert row.oni_proxy_used is False
    assert row.oni_season_used == row.oni_requested_season == "JAS"
    assert row.oni_year_used == row.oni_requested_year == 2026


def test_oni_future_unpublished_season_uses_latest_official_as_proxy():
    # Oct 2026 -> SON, not yet published (latest available is JAS) -> proxy.
    row = _build_row(oni_df=MULTI_SEASON_ONI_DF, snapshot=_snapshot(valid_time=datetime(2026, 10, 7)))
    assert row.oni_anomaly == 2.16  # NOAA's latest published anomaly, not fabricated/interpolated
    assert row.oni_proxy_used is True
    assert row.oni_requested_season == "SON"
    assert row.oni_requested_year == 2026


def test_oni_proxy_provenance_distinguishes_requested_from_used_season():
    row = _build_row(oni_df=MULTI_SEASON_ONI_DF, snapshot=_snapshot(valid_time=datetime(2026, 11, 1)))  # OND
    assert row.oni_proxy_used is True
    assert (row.oni_requested_season, row.oni_requested_year) == ("OND", 2026)
    assert (row.oni_season_used, row.oni_year_used) == ("JAS", 2026)
    assert row.oni_anomaly == 2.16


def test_oni_historical_interior_gap_is_not_proxied_and_still_raises():
    # A gap WITHIN already-published history (no row for 2019 at all), even
    # though a chronologically LATER row (2020) exists -- this must raise,
    # never silently pull in the 2020 value as if it were "latest known".
    gapped_oni = pd.DataFrame([
        {"season": "OND", "year": 2018, "anom": 0.5},
        {"season": "DJF", "year": 2020, "anom": -0.3},
    ])
    with pytest.raises(UnresolvedLiveFeatureError) as exc_info:
        _build_row(oni_df=gapped_oni, snapshot=_snapshot(valid_time=datetime(2019, 6, 15)))  # MJJ 2019
    assert "oni_anomaly" in exc_info.value.missing_features


def test_latest_published_oni_skips_nan_rows():
    oni_with_nan_latest = pd.DataFrame([
        {"season": "JJA", "year": 2026, "anom": 1.2},
        {"season": "JAS", "year": 2026, "anom": float("nan")},  # published row, but suppressed/missing value
    ])
    anom, season, year = latest_published_oni(oni_with_nan_latest)
    assert (anom, season, year) == (1.2, "JJA", 2026)


def test_latest_published_oni_empty_table_returns_none():
    assert latest_published_oni(pd.DataFrame(columns=["season", "year", "anom"])) is None


# --- calibration: band selection ---------------------------------------------

PRED_BANDS = [
    {"label": "0-5%", "lo": 0.0, "hi": 5.0},
    {"label": "5-20%", "lo": 5.0, "hi": 20.0},
    {"label": "20-40%", "lo": 20.0, "hi": 40.0},
    {"label": "40-100%", "lo": 40.0, "hi": 100.000000001},
]


@pytest.mark.parametrize("pred_med,expected_band", [
    (0.0, "0-5%"), (4.99, "0-5%"),
    (5.0, "5-20%"), (19.99, "5-20%"),
    (20.0, "20-40%"), (39.99, "20-40%"),
    (40.0, "40-100%"), (100.0, "40-100%"),
])
def test_select_predicted_band_boundaries(pred_med, expected_band):
    assert select_predicted_band(pred_med, PRED_BANDS) == expected_band


# --- calibration: application -------------------------------------------------


def _calibration(Q_global=2.0, Q_by_band=None):
    return {"Q_global": Q_global, "Q_by_band": Q_by_band or {}, "pred_bands": PRED_BANDS}


def test_apply_calibration_uses_band_specific_q_when_available():
    cal = apply_calibration(10.0, 15.0, 20.0, _calibration(Q_global=1.0, Q_by_band={"5-20%": 7.0}))
    assert cal.calibration_status == "stratified_conformal"
    assert cal.q_applied == 7.0
    assert cal.low == pytest.approx(3.0)
    assert cal.high == pytest.approx(27.0)


def test_apply_calibration_falls_back_to_global_when_band_missing():
    cal = apply_calibration(10.0, 15.0, 20.0, _calibration(Q_global=1.0, Q_by_band={"40-100%": 7.0}))
    assert cal.calibration_status == "stratified_conformal_global_fallback"
    assert cal.q_applied == 1.0


def test_apply_calibration_never_changes_the_median():
    cal = apply_calibration(10.0, 15.0, 20.0, _calibration(Q_global=50.0))
    assert cal.median == 15.0


def test_apply_calibration_clips_to_0_100():
    cal_low_end = apply_calibration(1.0, 2.0, 3.0, _calibration(Q_global=50.0))
    assert cal_low_end.low == 0.0
    cal_high_end = apply_calibration(97.0, 98.0, 99.0, _calibration(Q_global=50.0))
    assert cal_high_end.high == 100.0


def test_apply_calibration_preserves_monotonicity_even_with_large_q():
    for pred_med in (0.0, 1.0, 50.0, 99.0, 100.0):
        cal = apply_calibration(pred_med, pred_med, pred_med, _calibration(Q_global=1000.0))
        assert cal.low <= cal.median <= cal.high
        assert 0.0 <= cal.low and cal.high <= 100.0


def test_severe_band_has_caveat_low_band_does_not():
    severe = apply_calibration(50.0, 60.0, 70.0, _calibration(Q_global=1.0, Q_by_band={"40-100%": 14.3}))
    assert severe.severe_uncertainty_caveat is not None
    assert "severe" in severe.severe_uncertainty_caveat.lower() or "27%" in severe.severe_uncertainty_caveat

    low = apply_calibration(1.0, 2.0, 3.0, _calibration(Q_global=1.0, Q_by_band={"0-5%": 0.0}))
    assert low.severe_uncertainty_caveat is None


# --- real artifacts on disk (local files, no network) -----------------------


def test_real_model_artifact_loads_and_is_distinct_from_synthetic():
    model = pipeline.get_model()
    assert model.is_fitted
    assert model.version == "xgboost-quantile-real-v1.0"

    legacy = QuantileOutageModel.load(pipeline.LEGACY_SYNTHETIC_ARTIFACT_PATH)
    assert legacy.is_fitted
    assert legacy.version != model.version  # synthetic artifact remains available, untouched, different model


def test_real_calibration_metadata_loads():
    cal = pipeline.get_calibration()
    assert cal["approach"] == "stratified_conformal"
    assert "Q_global" in cal and "Q_by_band" in cal and "pred_bands" in cal
    assert len(cal["pred_bands"]) == 4


# --- run_impact_pipeline: honest failure without real forecast data ---------


def test_run_impact_pipeline_raises_without_forecast_points():
    with pytest.raises(pipeline.MissingForecastDataError):
        pipeline.run_impact_pipeline(county_fips=["12075"])


def test_run_impact_pipeline_raises_on_empty_forecast_points_list():
    with pytest.raises(pipeline.MissingForecastDataError):
        pipeline.run_impact_pipeline(county_fips=["12075"], forecast_points=[])


# --- run_impact_pipeline: full synthetic path (monkeypatched static tables/model) ---


class _FakeModel:
    version = "xgboost-quantile-real-v1.0-test"

    def predict_quantiles(self, df: pd.DataFrame) -> np.ndarray:
        # deterministic: median = max_wind_kt/2, low = -5 off, high = +5 off (pre-clip)
        wind = df["max_wind_kt"].to_numpy()
        med = np.clip(wind / 2.0, 0, 100)
        return np.column_stack([np.clip(med - 5, 0, 100), med, np.clip(med + 5, 0, 100)])


@pytest.fixture
def patched_pipeline(monkeypatch):
    centroids = pd.DataFrame([{"county_fips": COUNTY_FIPS, "county_lat": COUNTY_LAT, "county_lon": COUNTY_LON}])
    static = {
        "centroids": centroids,
        "nri": NRI_DF, "svi": SVI_DF, "oni": ONI_DF,
        "mcc": load_mcc_customers(io.StringIO(MCC_SAMPLE)),
    }
    monkeypatch.setattr(pipeline, "_CACHED_STATIC_TABLES", None)
    monkeypatch.setattr(pipeline, "get_static_tables", lambda: static)
    monkeypatch.setattr(pipeline, "get_name_lookup", lambda: {COUNTY_FIPS: {"name": "Levy County", "state": "FL"}})
    monkeypatch.setattr(pipeline, "get_model", lambda: _FakeModel())
    monkeypatch.setattr(pipeline, "get_calibration", lambda: _calibration(Q_global=1.0, Q_by_band={"5-20%": 2.0}))
    return static


def _forecast_points(**snapshot_kwargs):
    return [_snapshot(**snapshot_kwargs).forecast]


def test_run_impact_pipeline_output_matches_impact_contract(patched_pipeline):
    result = pipeline.run_impact_pipeline(
        county_fips=[COUNTY_FIPS],
        advisory={"storm_id": "AL992026", "storm_name": "ALPHA", "advisory_number": 7},
        forecast_points=_forecast_points(),
        lead_time_h=72,
    )
    validated = Impact.model_validate(result)
    assert validated.advisory_number == 7
    assert validated.model_version == "xgboost-quantile-real-v1.0-test"
    assert len(validated.counties) == 1
    county = validated.counties[0]
    assert county.fips == COUNTY_FIPS
    assert county.pct_customers_out.low <= county.pct_customers_out.median <= county.pct_customers_out.high
    assert county.calibration_status in {"stratified_conformal", "stratified_conformal_global_fallback"}
    assert validated.forecast_cycle_utc is not None
    assert validated.forecast_valid_time_utc is not None
    assert validated.requested_lead_time_h == 72.0


def test_run_impact_pipeline_raises_for_county_not_in_centroids(patched_pipeline):
    with pytest.raises(pipeline.MissingForecastDataError, match="99999"):
        pipeline.run_impact_pipeline(
            county_fips=["99999"], forecast_points=_forecast_points(), lead_time_h=72,
        )


def test_run_impact_pipeline_propagates_unresolved_feature_error(patched_pipeline):
    with pytest.raises(UnresolvedLiveFeatureError):
        pipeline.run_impact_pipeline(
            county_fips=[COUNTY_FIPS], forecast_points=_forecast_points(dir_deg=None), lead_time_h=72,
        )


def test_run_impact_pipeline_raises_when_requested_tau_not_in_latest_cycle(patched_pipeline):
    with pytest.raises(pipeline.MissingForecastDataError, match="tau_h"):
        pipeline.run_impact_pipeline(
            county_fips=[COUNTY_FIPS], forecast_points=_forecast_points(tau_h=72), lead_time_h=48,
        )
