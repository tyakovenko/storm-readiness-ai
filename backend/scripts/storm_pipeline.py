"""Phase 3L: per-storm training-row pipeline, factored out of the validated
Michael pipeline (Phase 3G/3K) so build_michael_dataset.py and
build_multi_storm_dataset.py call the exact same logic. No feature or target
logic is redesigned here -- this module only orchestrates the existing,
already-tested building blocks (hurdat2, atcf_forecast, county_geometry,
county_selection, training_row) for one storm at a time.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pandas as pd

from backend.models.atcf_forecast import load_atcf_forecasts, select_snapshots_for_horizons
from backend.models.county_geometry import load_county_centroids
from backend.models.county_selection import select_candidate_counties
from backend.models.hurdat2 import Hurdat2Storm, find_storm, select_us_landfall
from backend.models.outage_target import load_eaglei_outages_filtered
from backend.models.schema import FEATURE_COLUMNS
from backend.models.training_row import TrainingRow, UnresolvedFeatureError, build_training_row

# Same values used for Michael (Phase 3G/3K) -- not re-decided here.
CANDIDATE_RADIUS_NM = 300.0
TARGET_WINDOW_BEFORE_LANDFALL_H = 6
TARGET_WINDOW_AFTER_LANDFALL_H = 48
LEAD_TIMES_H = (72.0, 48.0, 24.0)


@dataclass
class StormDatasetResult:
    storm_id: str
    storm_name: str
    successes: list[TrainingRow] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)


def build_storm_dataset(
    storm_id: str,
    storm_name: str,
    hurdat2_storms: list[Hurdat2Storm],
    atcf_path: Path,
    centroids: pd.DataFrame,
    nri_df: pd.DataFrame,
    svi_df: pd.DataFrame,
    oni_df: pd.DataFrame,
    mcc_df: pd.DataFrame,
    denominator_df: pd.DataFrame,
    eaglei_local_csv_path: Path,
    candidate_radius_nm: float = CANDIDATE_RADIUS_NM,
    window_before_h: float = TARGET_WINDOW_BEFORE_LANDFALL_H,
    window_after_h: float = TARGET_WINDOW_AFTER_LANDFALL_H,
    lead_times_h: tuple[float, ...] = LEAD_TIMES_H,
) -> StormDatasetResult:
    """Build every (candidate county x resolved horizon) TrainingRow for one
    storm. Raises RuntimeError if the storm has no usable US landfall --
    callers (the multi-storm script) must catch this and exclude the storm
    rather than inventing a fallback impact time.

    centroids/nri_df/svi_df/oni_df/mcc_df/denominator_df are storm-independent
    and expected to be loaded once by the caller and reused across storms.
    eaglei_local_csv_path is storm-year-specific (several storms can share a
    year) -- read via load_eaglei_outages_filtered() so a whole annual file
    is never held in memory at once (Phase 3L's scalability requirement).
    """
    storm = find_storm(hurdat2_storms, storm_id)
    landfall = select_us_landfall(storm)
    if landfall is None:
        raise RuntimeError(f"{storm_id} ({storm_name}) has no usable CONUS HURDAT2 landfall -- cannot proceed")
    impact_time_utc = landfall.time
    landfall_lat, landfall_lon = landfall.lat, landfall.lon

    window_start = impact_time_utc - timedelta(hours=window_before_h)
    window_end = impact_time_utc + timedelta(hours=window_after_h)

    with gzip.open(atcf_path, "rt") as f:
        forecast_points = load_atcf_forecasts(f)
    snapshots = select_snapshots_for_horizons(forecast_points, impact_time_utc, lead_times_h)
    rejected_horizons = [h for h, snap in snapshots.items() if snap is None]
    resolved_snapshots = {h: snap for h, snap in snapshots.items() if snap is not None}

    candidates = select_candidate_counties(centroids, landfall_lat, landfall_lon, candidate_radius_nm)
    candidate_fips = set(candidates["county_fips"])

    # Memory-bounded read: only rows in this storm's window AND candidate
    # counties are ever materialized, regardless of the annual file's size.
    outages_df = load_eaglei_outages_filtered(
        eaglei_local_csv_path, window_start, window_end, candidate_fips=candidate_fips,
    )

    successes: list[TrainingRow] = []
    rejections: list[dict] = []
    for _, county in candidates.iterrows():
        for lead_time_h, snapshot in resolved_snapshots.items():
            try:
                row = build_training_row(
                    storm_id=storm_id, storm_name=storm_name,
                    county_fips=county["county_fips"],
                    county_lat=county["county_lat"], county_lon=county["county_lon"],
                    snapshot=snapshot, impact_time_utc=impact_time_utc,
                    window_start=window_start, window_end=window_end,
                    nri_df=nri_df, svi_df=svi_df, oni_df=oni_df,
                    mcc_df=mcc_df, outages_df=outages_df, denominator_df=denominator_df,
                )
                successes.append(row)
            except UnresolvedFeatureError as e:
                rejections.append({
                    "county_fips": county["county_fips"], "lead_time_h": lead_time_h,
                    "reason": "unresolved_features", "missing_features": list(e.missing_features),
                })
            except ValueError as e:
                rejections.append({
                    "county_fips": county["county_fips"], "lead_time_h": lead_time_h,
                    "reason": "target_error", "detail": str(e),
                })

    rows_by_horizon = {h: sum(1 for r in successes if r.lead_time_h == h) for h in lead_times_h}
    rejected_by_horizon_count: dict[float, int] = {}
    for rej in rejections:
        rejected_by_horizon_count[rej["lead_time_h"]] = rejected_by_horizon_count.get(rej["lead_time_h"], 0) + 1
    assumed_zero_count = sum(1 for r in successes if r.assumed_zero)
    missing_feature_tally: dict[str, int] = {}
    for rej in rejections:
        for feat in rej.get("missing_features", []):
            missing_feature_tally[feat] = missing_feature_tally.get(feat, 0) + 1
    denominator_source_counts: dict[str, int] = {}
    for r in successes:
        denominator_source_counts[r.customer_denominator_source] = (
            denominator_source_counts.get(r.customer_denominator_source, 0) + 1
        )
    wind_method_counts: dict[str, int] = {}
    for r in successes:
        wind_method_counts[r.wind_estimate_method] = wind_method_counts.get(r.wind_estimate_method, 0) + 1

    pct_values = pd.Series([r.pct_customers_out for r in successes], dtype=float)
    target_stats = {} if pct_values.empty else {
        "min": pct_values.min(), "median": pct_values.median(), "mean": pct_values.mean(),
        "p90": pct_values.quantile(0.90), "p95": pct_values.quantile(0.95), "max": pct_values.max(),
    }
    # County-level counts: pct_customers_out/customers_out_peak/customer_denominator
    # are identical across a county's 3 horizon rows (the target doesn't vary
    # by lead time -- see Phase 3K), so counting over `successes` directly
    # triple-counts every affected county. Dedupe to one row per county_fips
    # first (Phase 3M caught this: Helene's true county-level rate was 20,
    # not the 60 "successes"-level count this bug had been producing).
    rows_by_county: dict[str, TrainingRow] = {}
    for r in successes:
        rows_by_county.setdefault(r.county_fips, r)
    unique_county_rows = list(rows_by_county.values())

    n_at_0 = sum(1 for r in unique_county_rows if r.pct_customers_out == 0.0)
    n_at_100 = sum(1 for r in unique_county_rows if r.pct_customers_out == 100.0)
    n_raw_ratio_over_100 = sum(
        1 for r in unique_county_rows
        if r.customer_denominator > 0 and (r.customers_out_peak / r.customer_denominator) > 1.0
    )

    # Explicit validation pass (same checks as Michael's script) -- raises
    # (not silently continues) if any row fails, since that would indicate a
    # bug in the shared pipeline, not a per-storm data gap.
    for row in successes:
        assert set(row.to_feature_dict().keys()) == set(FEATURE_COLUMNS)
        assert row.lead_time_h in lead_times_h
        assert row.cycle_init_time_utc <= impact_time_utc - timedelta(hours=row.lead_time_h)
        assert 0.0 <= row.pct_customers_out <= 100.0
        assert isinstance(row.county_fips, str) and len(row.county_fips) == 5

    diagnostics = {
        "storm_id": storm_id, "storm_name": storm_name,
        "impact_time_utc": impact_time_utc.isoformat(),
        "landfall_lat": landfall_lat, "landfall_lon": landfall_lon,
        "selected_snapshots": {
            h: {
                "cycle_init_time_utc": snap.cycle_init_time_utc.isoformat(),
                "forecast_tau_h": snap.forecast_tau_h,
                "valid_time_utc": snap.valid_time_utc.isoformat(),
            }
            for h, snap in resolved_snapshots.items()
        },
        "rejected_horizons": rejected_horizons,
        "candidate_county_count": len(candidates),
        "rows_built_total": len(successes),
        "rows_built_by_horizon": rows_by_horizon,
        "rows_rejected_total": len(rejections),
        "rejected_by_horizon_count": rejected_by_horizon_count,
        "rejection_samples": rejections[:20],
        "assumed_zero_count": assumed_zero_count,
        "missing_feature_tally": missing_feature_tally,
        "denominator_source_counts": denominator_source_counts,
        "wind_estimate_method_counts": wind_method_counts,
        "target_stats": target_stats,
        "n_counties_at_0_pct": n_at_0,
        "n_counties_at_100_pct": n_at_100,
        "n_counties_raw_ratio_over_100": n_raw_ratio_over_100,
    }

    return StormDatasetResult(storm_id=storm_id, storm_name=storm_name,
                               successes=successes, rejections=rejections, diagnostics=diagnostics)
