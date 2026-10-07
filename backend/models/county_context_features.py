"""Phase 3E: static/context county features for the 13-feature XGBoost contract.

Produces the 7 FEATURE_COLUMNS (backend/models/schema.py) that are NOT specific
to one storm/forecast: population_log, customers_served_log, tree_canopy_pct,
nri_risk_score, nri_eal_building_log, svi_overall, oni_anomaly. The other 6
(max_wind_kt, gust_wind_kt, dist_to_track_nm, forward_speed_kt, quadrant_right,
lead_time_h) come from county_storm_features.py (Phase 3D).

Output values are already in their final, model-ready form -- population_log,
customers_served_log, and nri_eal_building_log are already log1p-transformed.
Do NOT additionally route these through schema.py's features_to_dataframe()/
CountyFeatures: that path applies its own log1p to raw population/
customers_served/nri_eal_building for the live inference stub, and would
double-transform these.

Unlike dataset.py's load_county_static_lookup() (used by the live inference
stub, which fills in reasonable defaults so the demo UI never breaks on a
missing county), every missing or sentinel source value here resolves to
None with an explicit entry in `missing` -- silently defaulting would bias a
training set for exactly the rows whose real source data was absent. This
module does not combine these into the final training table (Phase 3F); it
only makes each of the 7 values -- and whether each was actually resolvable
-- available for that later phase to decide on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from .outage_target import normalize_fips

# MVP placeholder: the tree-canopy dataset referenced in the original data
# contract is not present in the GCS bucket (see project notes). A constant
# is preferable to fabricating per-county variation XGBoost would overfit to;
# tree_canopy_is_placeholder on the result flags this for anyone consuming it.
TREE_CANOPY_PLACEHOLDER_PCT = 50.0

# FEMA NRI (POPULATION/HRCN_RISKS/HRCN_EALB) and CDC SVI (RPL_THEMES) both use
# negative sentinels for "not computed for this county" -- never a real value.
# 0 is a legitimate real value for both (e.g. an inland county can have a real
# zero hurricane risk score), so only negative/NaN is treated as missing.
SVI_VALID_RANGE = (0.0, 1.0)  # RPL_THEMES is a percentile rank; outside this is sentinel

# ONI seasons are rolling 3-month windows labeled by the calendar year of their
# MIDDLE month (e.g. NDJ 1950 = Nov 1950 + Dec 1950 + Jan 1951 -- year matches
# Dec, the middle month, not Jan). So the season whose middle month is a given
# date's month always carries that date's own calendar year as YR -- no
# cross-year adjustment needed despite the windows spanning year boundaries.
_MONTH_TO_SEASON = {
    1: "DJF", 2: "JFM", 3: "FMA", 4: "MAM", 5: "AMJ", 6: "MJJ",
    7: "JJA", 8: "JAS", 9: "ASO", 10: "SON", 11: "OND", 12: "NDJ",
}


@dataclass(frozen=True)
class CountyContextFeatures:
    """The 7 static/context FEATURE_COLUMNS for one county, resolved against a
    given snapshot date (for ONI only -- NRI/SVI/MCC are not time-varying in
    the sources available). Fields a source couldn't resolve are None and
    named in `missing`; tree_canopy_pct is never None (see module docstring)."""

    county_fips: str
    population_log: float | None
    customers_served_log: float | None
    tree_canopy_pct: float
    nri_risk_score: float | None
    nri_eal_building_log: float | None
    svi_overall: float | None
    oni_anomaly: float | None
    missing: tuple[str, ...]
    oni_season: str
    oni_year: int
    tree_canopy_is_placeholder: bool = True


def _nri_row(nri_df: pd.DataFrame, fips: str) -> pd.Series | None:
    rows = nri_df.loc[nri_df["fips"] == fips]
    return rows.iloc[0] if not rows.empty else None


def population_log_from_nri(nri_row: pd.Series | None) -> float | None:
    """log1p(POPULATION). None if the county has no NRI row, or POPULATION is
    missing/negative (a real population is never negative)."""
    if nri_row is None or pd.isnull(nri_row["POPULATION"]):
        return None
    population = float(nri_row["POPULATION"])
    return None if population < 0 else float(np.log1p(population))


def nri_risk_score_from_nri(nri_row: pd.Series | None) -> float | None:
    """HRCN_RISKS as-is (not log-transformed -- it's already a bounded risk
    score, unlike EALB's raw dollar magnitude). None if missing/negative."""
    if nri_row is None or pd.isnull(nri_row["HRCN_RISKS"]):
        return None
    score = float(nri_row["HRCN_RISKS"])
    return None if score < 0 else score


def nri_eal_building_log_from_nri(nri_row: pd.Series | None) -> float | None:
    """log1p(HRCN_EALB). None if missing/negative."""
    if nri_row is None or pd.isnull(nri_row["HRCN_EALB"]):
        return None
    eal = float(nri_row["HRCN_EALB"])
    return None if eal < 0 else float(np.log1p(eal))


def svi_overall_from_svi(svi_df: pd.DataFrame, fips: str) -> float | None:
    """RPL_THEMES as-is. None if the county has no SVI row, or the value is
    missing/outside [0, 1] (CDC's sentinel for suppressed/not-computed rows)."""
    rows = svi_df.loc[svi_df["fips"] == fips]
    if rows.empty or pd.isnull(rows.iloc[0]["RPL_THEMES"]):
        return None
    value = float(rows.iloc[0]["RPL_THEMES"])
    lo, hi = SVI_VALID_RANGE
    return value if lo <= value <= hi else None


def customers_served_log_from_mcc(mcc_df: pd.DataFrame, fips: str) -> float | None:
    """log1p(MCC Customers). `mcc_df` is the output of
    outage_target.load_mcc_customers() -- the archive-bundled, historical
    MCC.csv (not the fall-2025 live customer file; see outage_target.py's
    module docstring for why). None if the county has no MCC row."""
    rows = mcc_df.loc[mcc_df["county_fips"] == fips]
    if rows.empty or pd.isnull(rows.iloc[0]["mcc_customers"]):
        return None
    customers = float(rows.iloc[0]["mcc_customers"])
    return None if customers < 0 else float(np.log1p(customers))


def oni_anomaly_for_date(oni_df: pd.DataFrame, target_date: datetime) -> tuple[float | None, str, int]:
    """ONI anomaly for the 3-month season whose middle month is target_date's
    month (see _MONTH_TO_SEASON comment for the year-labeling convention).
    Returns (anomaly_or_None, season_code, season_year) -- season/year are
    always returned, even on a miss, so callers can see what was searched for."""
    season = _MONTH_TO_SEASON[target_date.month]
    year = target_date.year
    match = oni_df.loc[(oni_df["season"] == season) & (oni_df["year"] == year)]
    if match.empty or pd.isnull(match.iloc[0]["anom"]):
        return None, season, year
    return float(match.iloc[0]["anom"]), season, year


def build_county_context_features(
    county_fips: str,
    snapshot_date: datetime,
    nri_df: pd.DataFrame,
    svi_df: pd.DataFrame,
    mcc_df: pd.DataFrame,
    oni_df: pd.DataFrame,
) -> CountyContextFeatures:
    """Assemble the 7 static/context FEATURE_COLUMNS for one county at one
    snapshot date. Callers load nri_df/svi_df/oni_df via dataset.py's
    load_nri_table()/load_svi_table()/load_oni_table(), and mcc_df via
    outage_target.load_mcc_customers() on the archive's MCC.csv."""
    fips = normalize_fips(county_fips)
    nri_row = _nri_row(nri_df, fips)

    oni_anomaly, oni_season, oni_year = oni_anomaly_for_date(oni_df, snapshot_date)
    values = {
        "population_log": population_log_from_nri(nri_row),
        "customers_served_log": customers_served_log_from_mcc(mcc_df, fips),
        "nri_risk_score": nri_risk_score_from_nri(nri_row),
        "nri_eal_building_log": nri_eal_building_log_from_nri(nri_row),
        "svi_overall": svi_overall_from_svi(svi_df, fips),
        "oni_anomaly": oni_anomaly,
    }
    missing = tuple(name for name, value in values.items() if value is None)

    return CountyContextFeatures(
        county_fips=fips,
        tree_canopy_pct=TREE_CANOPY_PLACEHOLDER_PCT,
        oni_season=oni_season,
        oni_year=oni_year,
        missing=missing,
        **values,
    )
