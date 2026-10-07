"""Tests for the static/context county feature layer (Phase 3E).

Small synthetic NRI/SVI/MCC/ONI frames only -- no real GCS/archive data.
"""

from datetime import datetime

import math

import pandas as pd
import pytest

from backend.models.county_context_features import (
    TREE_CANOPY_PLACEHOLDER_PCT,
    build_county_context_features,
    customers_served_log_from_mcc,
    nri_eal_building_log_from_nri,
    nri_risk_score_from_nri,
    oni_anomaly_for_date,
    population_log_from_nri,
    svi_overall_from_svi,
)

NRI_DF = pd.DataFrame([
    {"fips": "12075", "POPULATION": 40000, "HRCN_EALB": 500000.0, "HRCN_RISKS": 25.0},
    {"fips": "12029", "POPULATION": -999, "HRCN_EALB": -999.0, "HRCN_RISKS": -999.0},  # sentinel row
    {"fips": "12017", "POPULATION": 15000, "HRCN_EALB": 0.0, "HRCN_RISKS": 0.0},  # real zeros
    {"fips": "12123", "POPULATION": None, "HRCN_EALB": None, "HRCN_RISKS": None},  # NaN row
])

SVI_DF = pd.DataFrame([
    {"fips": "12075", "RPL_THEMES": 0.65},
    {"fips": "12029", "RPL_THEMES": -999.0},  # sentinel
    {"fips": "12017", "RPL_THEMES": 0.0},  # real boundary value
])

MCC_DF = pd.DataFrame([
    {"county_fips": "12075", "mcc_customers": 1000.0},
    {"county_fips": "12017", "mcc_customers": 0.0},
])

ONI_DF = pd.DataFrame([
    {"season": "OND", "year": 2018, "anom": 0.8},
    {"season": "DJF", "year": 2019, "anom": 0.7},
    {"season": "JAS", "year": 2018, "anom": -0.2},
])


# --- population_log ---------------------------------------------------------


def test_population_log_applies_log1p_once():
    row = NRI_DF.loc[NRI_DF["fips"] == "12075"].iloc[0]
    assert population_log_from_nri(row) == pytest.approx(math.log1p(40000))


def test_population_log_none_for_missing_row():
    assert population_log_from_nri(None) is None


def test_population_log_none_for_sentinel():
    row = NRI_DF.loc[NRI_DF["fips"] == "12029"].iloc[0]
    assert population_log_from_nri(row) is None


def test_population_log_none_for_nan():
    row = NRI_DF.loc[NRI_DF["fips"] == "12123"].iloc[0]
    assert population_log_from_nri(row) is None


# --- nri_risk_score / nri_eal_building_log -----------------------------------


def test_nri_risk_score_passthrough_not_log_transformed():
    row = NRI_DF.loc[NRI_DF["fips"] == "12075"].iloc[0]
    assert nri_risk_score_from_nri(row) == 25.0


def test_nri_eal_building_log_applies_log1p():
    row = NRI_DF.loc[NRI_DF["fips"] == "12075"].iloc[0]
    assert nri_eal_building_log_from_nri(row) == pytest.approx(math.log1p(500000.0))


def test_nri_real_zero_is_not_treated_as_missing():
    # a real zero hurricane-risk score/EAL (e.g. inland county) must survive
    row = NRI_DF.loc[NRI_DF["fips"] == "12017"].iloc[0]
    assert nri_risk_score_from_nri(row) == 0.0
    assert nri_eal_building_log_from_nri(row) == pytest.approx(math.log1p(0.0))


def test_nri_sentinel_negative_values_are_missing():
    row = NRI_DF.loc[NRI_DF["fips"] == "12029"].iloc[0]
    assert nri_risk_score_from_nri(row) is None
    assert nri_eal_building_log_from_nri(row) is None


# --- svi_overall --------------------------------------------------------------


def test_svi_overall_passthrough():
    assert svi_overall_from_svi(SVI_DF, "12075") == 0.65


def test_svi_overall_boundary_zero_is_valid():
    assert svi_overall_from_svi(SVI_DF, "12017") == 0.0


def test_svi_overall_sentinel_is_missing():
    assert svi_overall_from_svi(SVI_DF, "12029") is None


def test_svi_overall_missing_fips_is_missing():
    assert svi_overall_from_svi(SVI_DF, "99999") is None


# --- customers_served_log (MCC join) -----------------------------------------


def test_customers_served_log_from_mcc_join():
    assert customers_served_log_from_mcc(MCC_DF, "12075") == pytest.approx(math.log1p(1000.0))


def test_customers_served_log_zero_customers_is_valid_not_missing():
    assert customers_served_log_from_mcc(MCC_DF, "12017") == pytest.approx(math.log1p(0.0))


def test_customers_served_log_missing_fips_is_missing():
    assert customers_served_log_from_mcc(MCC_DF, "12029") is None


# --- ONI season/date matching --------------------------------------------------


def test_oni_matches_november_to_ond_same_year():
    # November is OND's middle month (Oct-Nov-Dec), not NDJ's (Nov-Dec-Jan,
    # middle=Dec) -- a common off-by-one if you pick the season by "contains
    # this month" instead of "this month is the middle one".
    anomaly, season, year = oni_anomaly_for_date(ONI_DF, datetime(2018, 11, 15))
    assert (season, year) == ("OND", 2018)
    assert anomaly == 0.8


def test_oni_matches_january_to_djf_same_year_not_december():
    # January's season is DJF labeled with January's OWN year, not a shifted one
    anomaly, season, year = oni_anomaly_for_date(ONI_DF, datetime(2019, 1, 10))
    assert (season, year) == ("DJF", 2019)
    assert anomaly == 0.7


def test_oni_matches_by_season_not_just_year():
    # same year (2018) as the NDJ row, but a different season -- must not
    # collapse to "any row for 2018"
    anomaly, season, year = oni_anomaly_for_date(ONI_DF, datetime(2018, 8, 1))
    assert (season, year) == ("JAS", 2018)
    assert anomaly == -0.2


def test_oni_missing_season_year_combination_returns_none_with_diagnostics():
    anomaly, season, year = oni_anomaly_for_date(ONI_DF, datetime(2020, 3, 1))
    assert anomaly is None
    assert (season, year) == ("FMA", 2020)


# --- build_county_context_features (full assembly) ----------------------------


def test_build_full_assembly_happy_path_and_fips_join():
    result = build_county_context_features(
        county_fips=12075,  # int input, exercises normalize_fips zero-padding
        snapshot_date=datetime(2018, 11, 15),
        nri_df=NRI_DF, svi_df=SVI_DF, mcc_df=MCC_DF, oni_df=ONI_DF,
    )
    assert result.county_fips == "12075"
    assert result.population_log == pytest.approx(math.log1p(40000))
    assert result.customers_served_log == pytest.approx(math.log1p(1000.0))
    assert result.nri_risk_score == 25.0
    assert result.nri_eal_building_log == pytest.approx(math.log1p(500000.0))
    assert result.svi_overall == 0.65
    assert result.oni_anomaly == 0.8
    assert result.missing == ()


def test_build_full_assembly_flags_each_missing_field():
    result = build_county_context_features(
        county_fips="12029",  # sentinel NRI/SVI row, no MCC row
        snapshot_date=datetime(2018, 11, 15),
        nri_df=NRI_DF, svi_df=SVI_DF, mcc_df=MCC_DF, oni_df=ONI_DF,
    )
    assert set(result.missing) == {
        "population_log", "customers_served_log", "nri_risk_score",
        "nri_eal_building_log", "svi_overall",
    }
    assert result.oni_anomaly == 0.8  # ONI is not county-specific; still resolves


def test_build_full_assembly_tree_canopy_is_explicit_placeholder():
    result = build_county_context_features(
        county_fips="12075",
        snapshot_date=datetime(2018, 11, 15),
        nri_df=NRI_DF, svi_df=SVI_DF, mcc_df=MCC_DF, oni_df=ONI_DF,
    )
    assert result.tree_canopy_pct == TREE_CANOPY_PLACEHOLDER_PCT
    assert result.tree_canopy_is_placeholder is True
    assert "tree_canopy_pct" not in result.missing  # placeholder, not a source gap
