"""Phase 3F: assemble one XGBoost training row from the Phase 3 ETL components.

Orchestrates (does not reimplement) county_storm_features.py (Phase 3D, the 6
dynamic features), county_context_features.py (Phase 3E, the 7 static/context
features), and outage_target.py (the pct_customers_out target) into a single
row with exactly schema.py's 13 FEATURE_COLUMNS, the target, and provenance.

All inputs here are already-resolved objects/DataFrames (a ForecastSnapshot,
a county lat/lon, loaded NRI/SVI/ONI/MCC/EAGLE-I/denominator DataFrames, an
explicit outage window) -- this module does not parse ATCF, load shapefiles,
hit GCS, or decide the outage window; those remain the earlier phases' jobs.

No double log transform: county_context_features.py's population_log/
customers_served_log/nri_eal_building_log are already log1p-transformed, and
this module copies them straight into TrainingRow's same-named fields. It
never constructs a schema.py CountyFeatures or calls features_to_dataframe()
(that path applies its own log1p to RAW population/customers_served/
nri_eal_building for the live inference stub, which would double-transform
values that are already logged here).

No silent defaults: if any of the 13 FEATURE_COLUMNS resolves to None (e.g.
quadrant_right with no ATCF DIR, forward_speed_kt with no SPEED and no
adjacent point, or an NRI/SVI/ONI gap), build_training_row() raises
UnresolvedFeatureError naming every missing feature rather than returning a
row with an invented value standing in for real source data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .atcf_forecast import ForecastPoint, ForecastSnapshot
from .county_context_features import build_county_context_features
from .county_storm_features import compute_county_storm_features
from .outage_target import compute_county_outage_target, normalize_fips
from .schema import FEATURE_COLUMNS

assert tuple(FEATURE_COLUMNS) == (
    "max_wind_kt", "gust_wind_kt", "dist_to_track_nm", "forward_speed_kt", "quadrant_right",
    "population_log", "customers_served_log", "tree_canopy_pct", "nri_risk_score",
    "nri_eal_building_log", "svi_overall", "oni_anomaly", "lead_time_h",
), "schema.py's FEATURE_COLUMNS changed shape -- update this module's field mapping to match"


class UnresolvedFeatureError(ValueError):
    """Raised instead of building a row when one or more of the 13
    FEATURE_COLUMNS could not be resolved from source data."""

    def __init__(self, missing_features: tuple[str, ...], context: dict):
        self.missing_features = missing_features
        self.context = context
        super().__init__(
            f"Cannot build training row: unresolved required feature(s) {missing_features} "
            f"(context: {context})"
        )


@dataclass(frozen=True)
class TrainingRow:
    """One XGBoost training observation: the 13 model features (field names
    match FEATURE_COLUMNS exactly), the target, and provenance/audit fields.
    Provenance is listed after the target and is never consumed by the model
    -- use to_feature_series()/to_feature_dict() to get the model-only view."""

    # --- the 13 FEATURE_COLUMNS, exactly (see module-level assert above) ---
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

    # --- target ---
    pct_customers_out: float

    # --- provenance / audit (NOT model features) ---
    storm_id: str
    storm_name: str | None
    county_fips: str
    cycle_init_time_utc: datetime
    forecast_valid_time_utc: datetime
    forecast_tau_h: int
    impact_time_utc: datetime
    window_start: datetime
    window_end: datetime
    customers_out_peak: float
    customer_denominator: float
    customer_denominator_source: str
    assumed_zero: bool
    wind_estimate_method: str
    tree_canopy_is_placeholder: bool

    def to_feature_dict(self) -> dict:
        """Just the 13 model features, as a plain dict keyed by FEATURE_COLUMNS name."""
        return {col: getattr(self, col) for col in FEATURE_COLUMNS}

    def to_feature_series(self) -> pd.Series:
        """Just the 13 model features, ordered to match FEATURE_COLUMNS exactly --
        safe to stack into a DataFrame and index with df[FEATURE_COLUMNS]."""
        return pd.Series(self.to_feature_dict(), index=FEATURE_COLUMNS)


def build_training_row(
    storm_id: str,
    storm_name: str | None,
    county_fips: str,
    county_lat: float,
    county_lon: float,
    snapshot: ForecastSnapshot,
    impact_time_utc: datetime,
    window_start: datetime,
    window_end: datetime,
    nri_df: pd.DataFrame,
    svi_df: pd.DataFrame,
    oni_df: pd.DataFrame,
    mcc_df: pd.DataFrame,
    outages_df: pd.DataFrame,
    denominator_df: pd.DataFrame,
    adjacent_point: ForecastPoint | None = None,
) -> TrainingRow:
    """Build one TrainingRow for (storm, county, forecast snapshot, outage window).

    nri_df/svi_df/oni_df: dataset.py's load_nri_table()/load_svi_table()/
    load_oni_table() (or an equivalently-shaped DataFrame, e.g. in tests).
    mcc_df: outage_target.load_mcc_customers() output -- used ONLY for the
    customers_served_log feature (county_context_features.py); this is a
    separate use of MCC data from the outage-target denominator below, not
    affected by Phase 3K's denominator change.
    outages_df: outage_target.load_eaglei_outages() output.
    denominator_df: outage_target.build_customer_denominator_table() output
    -- the Phase 3K unified Fall-2025/MCC-fallback customer-count denominator
    used for pct_customers_out. Deliberately a separate parameter from
    mcc_df so the feature and the target can use different sources.

    Raises UnresolvedFeatureError if any of the 13 FEATURE_COLUMNS can't be
    resolved -- see module docstring. Target/provenance failures (e.g. no
    denominator for this county) surface as outage_target.py's own
    ValueError, since pct_customers_out has no valid "unresolved"
    representation to fall back to.
    """
    fips = normalize_fips(county_fips)

    storm_features = compute_county_storm_features(county_lat, county_lon, snapshot, adjacent_point)
    context_features = build_county_context_features(fips, impact_time_utc, nri_df, svi_df, mcc_df, oni_df)
    target = compute_county_outage_target(outages_df, denominator_df, fips, window_start, window_end)

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
        "oni_anomaly": context_features.oni_anomaly,
        "lead_time_h": storm_features.lead_time_h,
    }
    missing = tuple(name for name in FEATURE_COLUMNS if candidate_features[name] is None)
    if missing:
        raise UnresolvedFeatureError(
            missing,
            {
                "storm_id": storm_id,
                "county_fips": fips,
                "lead_time_h": snapshot.lead_time_h,
                "forecast_tau_h": snapshot.forecast_tau_h,
            },
        )

    return TrainingRow(
        **candidate_features,
        pct_customers_out=target.pct_customers_out,
        storm_id=storm_id,
        storm_name=storm_name,
        county_fips=fips,
        cycle_init_time_utc=snapshot.cycle_init_time_utc,
        forecast_valid_time_utc=snapshot.valid_time_utc,
        forecast_tau_h=snapshot.forecast_tau_h,
        impact_time_utc=impact_time_utc,
        window_start=window_start,
        window_end=window_end,
        customers_out_peak=target.customers_out_peak,
        customer_denominator=target.customer_denominator,
        customer_denominator_source=target.customer_denominator_source,
        assumed_zero=target.assumed_zero,
        wind_estimate_method=storm_features.wind_estimate_method,
        tree_canopy_is_placeholder=context_features.tree_canopy_is_placeholder,
    )
