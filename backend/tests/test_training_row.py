"""Tests for the unified training-row builder (Phase 3F).

Synthetic ForecastSnapshot + NRI/SVI/ONI/MCC/EAGLE-I frames only -- no real
GCS/archive data (see test_training_row_real_data_smoke.py for that).
"""

import io
import math
from datetime import datetime, timedelta

import pandas as pd
import pytest

from backend.models.atcf_forecast import ForecastPoint, ForecastSnapshot, WindRadii
from backend.models.outage_target import load_eaglei_outages, load_mcc_customers
from backend.models.schema import FEATURE_COLUMNS
from backend.models.training_row import (
    TrainingRow,
    UnresolvedFeatureError,
    build_training_row,
)

STORM_LAT, STORM_LON = 25.0, -85.0
VMAX = 100.0
RADII = {
    64: WindRadii("NEQ", ne_nm=30.0, se_nm=30.0, sw_nm=25.0, nw_nm=25.0),
    50: WindRadii("NEQ", ne_nm=60.0, se_nm=60.0, sw_nm=50.0, nw_nm=50.0),
    34: WindRadii("NEQ", ne_nm=120.0, se_nm=120.0, sw_nm=100.0, nw_nm=100.0),
}
COUNTY_FIPS = "12075"
COUNTY_LAT, COUNTY_LON = STORM_LAT + 10.0 / 60.0, STORM_LON  # ~10nm due north

NRI_DF = pd.DataFrame([
    {"fips": COUNTY_FIPS, "POPULATION": 40000, "HRCN_EALB": 500000.0, "HRCN_RISKS": 25.0},
])
SVI_DF = pd.DataFrame([{"fips": COUNTY_FIPS, "RPL_THEMES": 0.65}])

EAGLEI_SAMPLE = f"""fips_code,county,state,customers_out,run_start_time
{COUNTY_FIPS},Levy,Florida,500,2018-10-10 06:00:00
"""
MCC_SAMPLE = f"""County_FIPS,Customers
{COUNTY_FIPS},1000
"""
ONI_DF = pd.DataFrame([{"season": "SON", "year": 2018, "anom": 0.6}])


def _snapshot(*, dir_deg=0.0, speed_kt=10.0, tau_h=72, lead_time_h=72) -> ForecastSnapshot:
    cycle = datetime(2018, 10, 7, 18)
    point = ForecastPoint(
        storm_id="AL142018", basin="AL", cyclone_num=14, tech="OFCL",
        cycle_init_time_utc=cycle, tau_h=tau_h, valid_time_utc=cycle + timedelta(hours=tau_h),
        lat=STORM_LAT, lon=STORM_LON, vmax_kt=VMAX, mslp_mb=950.0, storm_type="HU",
        dir_deg=dir_deg, speed_kt=speed_kt, storm_name="MICHAEL", wind_radii=dict(RADII),
    )
    return ForecastSnapshot(
        lead_time_h=lead_time_h, forecast_tau_h=tau_h, cycle_init_time_utc=cycle,
        valid_time_utc=point.valid_time_utc, forecast=point,
    )


def _denominator_df_from_mcc(mcc_df: pd.DataFrame) -> pd.DataFrame:
    df = mcc_df.rename(columns={"mcc_customers": "customer_denominator"}).copy()
    df["customer_denominator_source"] = "mcc_test"
    return df


def _build_row(**overrides) -> TrainingRow:
    snapshot = overrides.pop("snapshot", _snapshot())
    mcc_df = overrides.pop("mcc_df", load_mcc_customers(io.StringIO(MCC_SAMPLE)))
    denominator_df = overrides.pop("denominator_df", _denominator_df_from_mcc(mcc_df))
    outages_df = overrides.pop("outages_df", load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE)))
    nri_df = overrides.pop("nri_df", NRI_DF)
    svi_df = overrides.pop("svi_df", SVI_DF)
    oni_df = overrides.pop("oni_df", ONI_DF)
    impact_time = overrides.pop("impact_time_utc", datetime(2018, 10, 10, 18))
    window_start = overrides.pop("window_start", datetime(2018, 10, 10, 0, 0))
    window_end = overrides.pop("window_end", datetime(2018, 10, 10, 23, 59))

    return build_training_row(
        storm_id="AL142018",
        storm_name="MICHAEL",
        county_fips=COUNTY_FIPS,
        county_lat=COUNTY_LAT,
        county_lon=COUNTY_LON,
        snapshot=snapshot,
        impact_time_utc=impact_time,
        window_start=window_start,
        window_end=window_end,
        nri_df=nri_df,
        svi_df=svi_df,
        oni_df=oni_df,
        mcc_df=mcc_df,
        outages_df=outages_df,
        denominator_df=denominator_df,
        **overrides,
    )


# --- 13-feature FEATURE_COLUMNS compatibility --------------------------------


def test_feature_dict_has_exactly_the_13_feature_columns():
    row = _build_row()
    assert set(row.to_feature_dict().keys()) == set(FEATURE_COLUMNS)
    assert len(row.to_feature_dict()) == 13


def test_feature_series_matches_feature_columns_order_and_is_model_ready():
    row = _build_row()
    series = row.to_feature_series()
    assert list(series.index) == FEATURE_COLUMNS
    # a DataFrame built from this row must subscript cleanly the way
    # outage_model.py's fit()/predict_quantiles() do: X[FEATURE_COLUMNS]
    df = pd.DataFrame([series])
    assert list(df[FEATURE_COLUMNS].columns) == FEATURE_COLUMNS


def test_provenance_fields_are_not_in_the_feature_view():
    row = _build_row()
    feature_keys = set(row.to_feature_dict().keys())
    for provenance_field in ("storm_id", "county_fips", "pct_customers_out", "assumed_zero"):
        assert provenance_field not in feature_keys


# --- no double log transform --------------------------------------------------


def test_population_log_is_transformed_exactly_once():
    row = _build_row()
    assert row.population_log == pytest.approx(math.log1p(40000))


def test_customers_served_log_is_transformed_exactly_once():
    row = _build_row()
    assert row.customers_served_log == pytest.approx(math.log1p(1000.0))


def test_nri_eal_building_log_is_transformed_exactly_once():
    row = _build_row()
    assert row.nri_eal_building_log == pytest.approx(math.log1p(500000.0))


def test_nri_risk_score_and_svi_are_not_log_transformed():
    row = _build_row()
    assert row.nri_risk_score == 25.0
    assert row.svi_overall == 0.65


# --- target ------------------------------------------------------------------


def test_target_pct_customers_out_matches_outage_target_computation():
    row = _build_row()
    # 500 peak customers_out / 1000 denominator = 50%
    assert row.pct_customers_out == pytest.approx(50.0)
    assert row.customers_out_peak == 500.0
    assert row.customer_denominator == 1000.0
    assert row.customer_denominator_source == "mcc_test"
    assert row.assumed_zero is False


# --- provenance preserved ------------------------------------------------------


def test_provenance_fields_preserved():
    row = _build_row()
    assert row.storm_id == "AL142018"
    assert row.storm_name == "MICHAEL"
    assert row.county_fips == COUNTY_FIPS
    assert row.cycle_init_time_utc == datetime(2018, 10, 7, 18)
    assert row.forecast_tau_h == 72
    assert row.impact_time_utc == datetime(2018, 10, 10, 18)
    assert row.window_start == datetime(2018, 10, 10, 0, 0)
    assert row.window_end == datetime(2018, 10, 10, 23, 59)
    assert row.wind_estimate_method in ("radius_interpolation", "vmax_decay_fallback")
    assert row.tree_canopy_is_placeholder is True


def test_county_fips_provenance_normalizes_short_input():
    row = _build_row()
    # confirm normalize_fips is actually applied, not just passed through
    mcc_df = load_mcc_customers(io.StringIO(MCC_SAMPLE))
    row_from_int = build_training_row(
        storm_id="AL142018", storm_name="MICHAEL", county_fips=int(COUNTY_FIPS),
        county_lat=COUNTY_LAT, county_lon=COUNTY_LON, snapshot=_snapshot(),
        impact_time_utc=datetime(2018, 10, 10, 18),
        window_start=datetime(2018, 10, 10, 0, 0), window_end=datetime(2018, 10, 10, 23, 59),
        nri_df=NRI_DF, svi_df=SVI_DF, oni_df=ONI_DF,
        mcc_df=mcc_df,
        outages_df=load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE)),
        denominator_df=_denominator_df_from_mcc(mcc_df),
    )
    assert row_from_int.county_fips == COUNTY_FIPS == row.county_fips


# --- unresolved required feature prevents a valid row -------------------------


def test_missing_dir_quadrant_right_raises_unresolved_feature_error():
    with pytest.raises(UnresolvedFeatureError) as exc_info:
        _build_row(snapshot=_snapshot(dir_deg=None))
    assert "quadrant_right" in exc_info.value.missing_features


def test_missing_speed_and_no_adjacent_point_raises_unresolved_feature_error():
    with pytest.raises(UnresolvedFeatureError) as exc_info:
        _build_row(snapshot=_snapshot(speed_kt=None))
    assert "forward_speed_kt" in exc_info.value.missing_features


def test_missing_nri_row_raises_unresolved_feature_error():
    empty_nri = pd.DataFrame(columns=["fips", "POPULATION", "HRCN_EALB", "HRCN_RISKS"])
    with pytest.raises(UnresolvedFeatureError) as exc_info:
        _build_row(nri_df=empty_nri)
    missing = set(exc_info.value.missing_features)
    assert {"population_log", "nri_risk_score", "nri_eal_building_log"} <= missing


def test_missing_svi_row_raises_unresolved_feature_error():
    empty_svi = pd.DataFrame(columns=["fips", "RPL_THEMES"])
    with pytest.raises(UnresolvedFeatureError) as exc_info:
        _build_row(svi_df=empty_svi)
    assert "svi_overall" in exc_info.value.missing_features


def test_missing_oni_season_raises_unresolved_feature_error():
    empty_oni = pd.DataFrame(columns=["season", "year", "anom"])
    with pytest.raises(UnresolvedFeatureError) as exc_info:
        _build_row(oni_df=empty_oni)
    assert "oni_anomaly" in exc_info.value.missing_features


def test_unresolved_error_reports_all_missing_features_at_once():
    empty_nri = pd.DataFrame(columns=["fips", "POPULATION", "HRCN_EALB", "HRCN_RISKS"])
    empty_svi = pd.DataFrame(columns=["fips", "RPL_THEMES"])
    with pytest.raises(UnresolvedFeatureError) as exc_info:
        _build_row(snapshot=_snapshot(dir_deg=None), nri_df=empty_nri, svi_df=empty_svi)
    missing = set(exc_info.value.missing_features)
    assert missing == {
        "quadrant_right", "population_log", "nri_risk_score",
        "nri_eal_building_log", "svi_overall",
    }


def test_denominator_source_is_recorded_in_provenance():
    # a denominator_df using a different source value propagates through to
    # the row's provenance untouched -- training_row.py doesn't care which
    # source produced it, just records it
    fall2025_style_df = pd.DataFrame([
        {"county_fips": COUNTY_FIPS, "customer_denominator": 1200.0, "customer_denominator_source": "fall2025"},
    ])
    row = _build_row(denominator_df=fall2025_style_df)
    assert row.customer_denominator == 1200.0
    assert row.customer_denominator_source == "fall2025"
    assert row.pct_customers_out == pytest.approx(100 * 500.0 / 1200.0)


def test_missing_denominator_row_raises_from_outage_target_not_silently():
    # no denominator row at all for this county -- outage_target.py's own
    # ValueError ("No customer denominator found") must still surface, not be swallowed
    empty_denominator = pd.DataFrame(columns=["county_fips", "customer_denominator", "customer_denominator_source"])
    with pytest.raises(ValueError, match="No customer denominator found"):
        _build_row(denominator_df=empty_denominator)


# --- full synthetic end-to-end assembly across Phase 3 modules -----------------


def test_full_synthetic_end_to_end_assembly():
    row = _build_row()

    # cross-check against the sub-modules directly, not just internal consistency
    from backend.models.county_storm_features import compute_county_storm_features

    expected_storm = compute_county_storm_features(COUNTY_LAT, COUNTY_LON, _snapshot())
    assert row.max_wind_kt == expected_storm.max_wind_kt
    assert row.gust_wind_kt == pytest.approx(row.max_wind_kt * 1.25, abs=0.01)
    assert row.dist_to_track_nm == pytest.approx(expected_storm.dist_to_track_nm)
    assert row.forward_speed_kt == 10.0
    assert row.quadrant_right in (0, 1)
    assert row.lead_time_h == 72

    assert row.population_log == pytest.approx(math.log1p(40000))
    assert row.tree_canopy_pct == 50.0
    assert row.nri_risk_score == 25.0
    assert row.svi_overall == 0.65
    assert row.oni_anomaly == 0.6

    assert row.pct_customers_out == pytest.approx(50.0)

    # the whole point of this phase: exactly 13 features, ready for the model
    series = row.to_feature_series()
    assert len(series) == 13
    assert not series.isnull().any()
