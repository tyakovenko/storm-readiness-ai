"""Phase 3Q: live (runtime) feature construction and post-hoc calibration.

This module is the live-inference counterpart to training_row.py: it builds
the exact same 13 FEATURE_COLUMNS from the exact same Phase 3D/3E utilities
(county_storm_features.py, county_context_features.py), but WITHOUT computing
a target -- there is no outcome yet to compute at inference time. If any of
the 13 features cannot be resolved from real source data, this raises
UnresolvedLiveFeatureError rather than inventing a value (same policy as
training_row.py's UnresolvedFeatureError).

It also applies the Phase 3P stratified-conformal calibration JSON to a
model's raw q10/q50/q90 output, with the median always left untouched.

Phase 3U: ONI publication-lag policy (LIVE/SCENARIO INFERENCE ONLY).
ONI is a 3-month running mean, so NOAA's latest officially published season
structurally lags the calendar by ~1-2 months -- a live forecast's valid
date can require a season NOAA hasn't released yet. county_context_features.
build_county_context_features() and oni_anomaly_for_date() are UNCHANGED and
still used exactly as before (training_row.py calls them identically, so
historical training behavior is untouched by this file). Only here, after
that call returns a miss, do we check whether the requested season is
chronologically AFTER the latest season actually present in oni_df:
  - if yes (not yet published): use that latest published anomaly as an
    explicitly-flagged "latest known ENSO state" proxy (oni_proxy_used=True
    on the returned LiveFeatureRow) -- no interpolation/extrapolation, just
    the most recent real observation.
  - if no (an interior/historical gap in otherwise-published data): do NOT
    proxy; oni_anomaly stays unresolved and still raises
    UnresolvedLiveFeatureError, exactly as before Phase 3U.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .atcf_forecast import ForecastPoint, ForecastSnapshot
from .county_context_features import build_county_context_features
from .county_storm_features import compute_county_storm_features
from .outage_target import normalize_fips
from .schema import FEATURE_COLUMNS

# Phase 3P found below-nominal interval coverage in these predicted-severity
# bands even after calibration (20-40%: ~54% vs the 80% nominal target;
# 40-100%: ~27%) -- callers must not present the calibrated interval as a
# reliable uncertainty estimate for counties landing in them.
SEVERE_UNCERTAINTY_CAVEATS: dict[str, str] = {
    "40-100%": (
        "Validation (leave-one-storm-out, Phase 3N-3P) found only ~27% empirical coverage for the "
        "most severe outages even after calibration. Treat this interval as a rough, experimental "
        "bound for this high-impact county, not a reliable uncertainty estimate."
    ),
    "20-40%": (
        "Validation found below-nominal (~54% vs. an 80% target) interval coverage in this band. "
        "Treat this uncertainty interval as indicative, not precise."
    ),
}


# Calendar order of NOAA's 12 rolling 3-month ONI seasons, DJF first (matches
# county_context_features.py's _MONTH_TO_SEASON convention). Used only to
# compare "is the requested season after the latest published one" -- never
# to interpolate/extrapolate a value for a season in between.
_SEASON_ORDER = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]


def _oni_sort_key(season: str, year: int) -> tuple[int, int]:
    return (year, _SEASON_ORDER.index(season))


def latest_published_oni(oni_df: pd.DataFrame) -> tuple[float, str, int] | None:
    """The chronologically latest (anomaly, season, year) actually present in
    oni_df, skipping any row with a missing/NaN anomaly. None if oni_df has
    no usable rows at all (e.g. malformed/empty).

    This never changes oni_anomaly_for_date()'s own exact-match behavior and
    is not called anywhere in the historical training path -- it only backs
    the live-inference "latest known ENSO state" proxy below.
    """
    usable = oni_df.dropna(subset=["anom"])
    if usable.empty:
        return None
    latest = max(usable.itertuples(index=False), key=lambda r: _oni_sort_key(r.season, r.year))
    return float(latest.anom), latest.season, int(latest.year)


class UnresolvedLiveFeatureError(ValueError):
    """Raised instead of predicting when one or more of the 13 FEATURE_COLUMNS
    cannot be resolved from real source data for this county/forecast. Never
    silently substituted with a default/hardcoded value."""

    def __init__(self, missing_features: tuple[str, ...], context: dict):
        self.missing_features = missing_features
        self.context = context
        super().__init__(
            f"Cannot build live feature row: unresolved required feature(s) {missing_features} "
            f"(context: {context})"
        )


@dataclass(frozen=True)
class LiveFeatureRow:
    """One live-inference observation: the 13 model features (field names
    match FEATURE_COLUMNS exactly) plus provenance. No target -- this is a
    prediction input, not a training row."""

    max_wind_kt: float
    gust_wind_kt: float
    dist_to_track_nm: float
    forward_speed_kt: float
    quadrant_right: int
    population_log: float
    customers_served_log: float
    tree_canopy_pct: float
    nri_risk_score: float
    nri_eal_building_log: float
    svi_overall: float
    oni_anomaly: float
    lead_time_h: float

    storm_id: str
    storm_name: str | None
    county_fips: str
    cycle_init_time_utc: datetime
    forecast_valid_time_utc: datetime
    forecast_tau_h: int
    wind_estimate_method: str
    tree_canopy_is_placeholder: bool

    # Phase 3U ONI provenance -- oni_proxy_used=False means oni_anomaly is an
    # exact match for oni_requested_season/year (oni_season_used ==
    # oni_requested_season). True means the requested season was not yet
    # officially published and oni_anomaly is NOAA's latest published season
    # (oni_season_used/oni_year_used) used as a "latest known ENSO state" proxy.
    oni_requested_season: str
    oni_requested_year: int
    oni_season_used: str
    oni_year_used: int
    oni_proxy_used: bool

    def to_feature_dict(self) -> dict:
        return {col: getattr(self, col) for col in FEATURE_COLUMNS}

    def to_feature_series(self) -> pd.Series:
        return pd.Series(self.to_feature_dict(), index=FEATURE_COLUMNS)


def build_live_feature_row(
    storm_id: str,
    storm_name: str | None,
    county_fips: str,
    county_lat: float,
    county_lon: float,
    snapshot: ForecastSnapshot,
    nri_df: pd.DataFrame,
    svi_df: pd.DataFrame,
    mcc_df: pd.DataFrame,
    oni_df: pd.DataFrame,
    adjacent_point: ForecastPoint | None = None,
) -> LiveFeatureRow:
    """Build one LiveFeatureRow for (storm, county, forecast snapshot).

    Context features (population/customers/NRI/SVI/ONI) are resolved against
    snapshot.valid_time_utc -- the forecast's OWN predicted valid time at this
    horizon -- as the "when" anchor. This is a deliberate, honest substitute
    for training_row.py's impact_time_utc (the historical TRUE landfall time,
    unknowable for an in-progress storm): it only uses information already in
    the forecast, and is only used to pick the right slow-moving ONI season,
    never to see the actual future outcome.

    Raises UnresolvedLiveFeatureError if any of the 13 FEATURE_COLUMNS can't
    be resolved -- see module docstring.
    """
    fips = normalize_fips(county_fips)

    storm_features = compute_county_storm_features(county_lat, county_lon, snapshot, adjacent_point)
    context_features = build_county_context_features(
        fips, snapshot.valid_time_utc, nri_df, svi_df, mcc_df, oni_df
    )

    # Phase 3U: live-only "latest known ENSO state" proxy. Only engages when
    # the exact requested season is missing AND that season is strictly
    # chronologically after the latest season oni_df actually has -- i.e. it
    # has not been officially published yet, not a gap inside already-
    # published history (that case is left alone and still raises below).
    oni_anomaly = context_features.oni_anomaly
    oni_season_used = context_features.oni_season
    oni_year_used = context_features.oni_year
    oni_proxy_used = False

    if oni_anomaly is None:
        latest = latest_published_oni(oni_df)
        if latest is not None:
            latest_anom, latest_season, latest_year = latest
            requested_key = _oni_sort_key(context_features.oni_season, context_features.oni_year)
            latest_key = _oni_sort_key(latest_season, latest_year)
            if requested_key > latest_key:
                oni_anomaly = latest_anom
                oni_season_used = latest_season
                oni_year_used = latest_year
                oni_proxy_used = True

    candidate_features = {
        "max_wind_kt": storm_features.max_wind_kt,
        "gust_wind_kt": storm_features.gust_wind_kt,
        "dist_to_track_nm": storm_features.dist_to_track_nm,
        "forward_speed_kt": storm_features.forward_speed_kt,
        "quadrant_right": storm_features.quadrant_right,
        "population_log": context_features.population_log,
        "customers_served_log": context_features.customers_served_log,
        "tree_canopy_pct": context_features.tree_canopy_pct,
        "nri_risk_score": context_features.nri_risk_score,
        "nri_eal_building_log": context_features.nri_eal_building_log,
        "svi_overall": context_features.svi_overall,
        "oni_anomaly": oni_anomaly,
        "lead_time_h": storm_features.lead_time_h,
    }
    missing = tuple(name for name in FEATURE_COLUMNS if candidate_features[name] is None)
    if missing:
        raise UnresolvedLiveFeatureError(
            missing,
            {
                "storm_id": storm_id,
                "county_fips": fips,
                "lead_time_h": snapshot.lead_time_h,
                "forecast_tau_h": snapshot.forecast_tau_h,
            },
        )

    return LiveFeatureRow(
        **candidate_features,
        storm_id=storm_id,
        storm_name=storm_name,
        county_fips=fips,
        cycle_init_time_utc=snapshot.cycle_init_time_utc,
        forecast_valid_time_utc=snapshot.valid_time_utc,
        forecast_tau_h=snapshot.forecast_tau_h,
        wind_estimate_method=storm_features.wind_estimate_method,
        tree_canopy_is_placeholder=context_features.tree_canopy_is_placeholder,
        oni_requested_season=context_features.oni_season,
        oni_requested_year=context_features.oni_year,
        oni_season_used=oni_season_used,
        oni_year_used=oni_year_used,
        oni_proxy_used=oni_proxy_used,
    )


@dataclass(frozen=True)
class CalibratedInterval:
    """Phase 3P calibration applied to one county's raw model output. Median
    is always exactly the raw model median -- calibration only ever touches
    low/high."""

    low: float
    median: float
    high: float
    predicted_band: str
    calibration_status: str  # "stratified_conformal" | "stratified_conformal_global_fallback"
    q_applied: float
    severe_uncertainty_caveat: str | None


def select_predicted_band(pred_med: float, pred_bands: list[dict]) -> str:
    """Which band the model's OWN predicted median falls into -- the only
    thing observable at inference time (never the unknown true outcome)."""
    for band in pred_bands:
        if band["lo"] <= pred_med < band["hi"]:
            return band["label"]
    return pred_bands[-1]["label"]  # pred_med at the very top edge (100.0)


def apply_calibration(pred_low: float, pred_med: float, pred_high: float, calibration: dict) -> CalibratedInterval:
    """Apply Phase 3P's stratified-conformal correction to [pred_low, pred_high].

    pred_med is never modified. Falls back to the global correction when the
    predicted band had too few calibration-pool rows to trust its own
    quantile (same policy used when the calibration was derived, see
    calibration_experiments.py). Clips to [0, 100] and re-enforces
    low <= median <= high after the additive correction.
    """
    band = select_predicted_band(pred_med, calibration["pred_bands"])
    q_by_band = calibration.get("Q_by_band") or {}
    if band in q_by_band:
        q = q_by_band[band]
        status = "stratified_conformal"
    else:
        q = calibration["Q_global"]
        status = "stratified_conformal_global_fallback"

    cal_low = pred_low - q
    cal_high = pred_high + q
    cal_low, cal_high = min(cal_low, cal_high), max(cal_low, cal_high)
    cal_low = max(0.0, min(cal_low, pred_med))
    cal_high = min(100.0, max(cal_high, pred_med))

    return CalibratedInterval(
        low=round(cal_low, 1),
        median=round(pred_med, 1),
        high=round(cal_high, 1),
        predicted_band=band,
        calibration_status=status,
        q_applied=round(float(q), 3),
        severe_uncertainty_caveat=SEVERE_UNCERTAINTY_CAVEATS.get(band),
    )
