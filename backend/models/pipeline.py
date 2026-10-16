"""Phase 3Q: end-to-end LIVE inference pipeline for Storm Readiness AI.

Uses the validated real-data model (outage_xgb_real_v1.joblib, Phase 3N) and
its Phase 3P stratified-conformal calibration, built from genuine ATCF
forecast data and real county/context sources (county_storm_features.py,
county_context_features.py, county_geometry.py) -- never from hardcoded
county geometry or invented feature values.

Historical-vs-live timing: training anchored each snapshot to the storm's
actual (future, at training time) HURDAT2 landfall. A live, in-progress
storm has no known future impact time to anchor to. select_live_snapshot()
below resolves this the honest way: it picks the forecast point at
TAU == requested lead_time_h from the latest available advisory cycle and
uses that point's OWN valid_time_utc as the "when" anchor -- information the
forecast already contains, never a future ground truth.

If the supplied forecast lacks genuine ATCF fields (storm track position,
intensity, heading), or a county's real NRI/SVI/MCC/ONI source data has a
gap, this raises rather than falling back to the old hardcoded 4-county
Florida distance table and defaults that lived here before Phase 3Q.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .atcf_forecast import ForecastPoint, ForecastSnapshot
from .county_geometry import load_county_centroids
from .dataset import (
    LOCAL_DATA_DIR,
    load_county_static_lookup,
    load_nri_table,
    load_oni_table,
    load_svi_table,
)
from .live_inference import (
    CalibratedInterval,
    UnresolvedLiveFeatureError,
    apply_calibration,
    build_live_feature_row,
)
from .outage_model import QuantileOutageModel
from .outage_target import load_mcc_customers, normalize_fips
from .schema import CountyFeatures, FEATURE_COLUMNS

log = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
REAL_ARTIFACT_PATH = ARTIFACTS_DIR / "outage_xgb_real_v1.joblib"
REAL_CALIBRATION_PATH = ARTIFACTS_DIR / "outage_xgb_real_v1_calibration.json"
# Kept on disk, still independently loadable (QuantileOutageModel.load(LEGACY_SYNTHETIC_ARTIFACT_PATH))
# for anything that still wants the old synthetic-bootstrap model -- just no longer what this
# real inference path loads or uses.
LEGACY_SYNTHETIC_ARTIFACT_PATH = ARTIFACTS_DIR / "outage_xgb_v1.joblib"

CENSUS_SHP_PATH = LOCAL_DATA_DIR / "raw" / "census" / "counties" / "cb_2025_us_county_500k.shp"
MCC_LOCAL_PATH = LOCAL_DATA_DIR / "raw" / "census" / "EAGLE I" / "MCC.csv"

DEFAULT_FIPS_TARGETS = ["12075", "12029", "12017", "12123"]  # which counties to report on by default (display choice, not a model feature)

_CACHED_MODEL: QuantileOutageModel | None = None
_CACHED_CALIBRATION: dict | None = None
_CACHED_STATIC_TABLES: dict[str, Any] | None = None
_CACHED_NAME_LOOKUP: dict[str, dict] | None = None


class MissingForecastDataError(RuntimeError):
    """Raised instead of predicting when the supplied forecast input lacks
    the real ATCF fields the model's features require (storm track position,
    intensity, wind radii, heading/speed), or a requested county has no
    resolvable geometry/context data. Never silently substituted with the
    old hardcoded Florida geometry or a default value."""


def get_model() -> QuantileOutageModel:
    """Load (and cache) the validated real-data model. Raises rather than
    training a bootstrap model on the fly if the artifact is missing --
    an inference path must never silently swap in a different model."""
    global _CACHED_MODEL
    if _CACHED_MODEL is None:
        if not REAL_ARTIFACT_PATH.exists():
            raise FileNotFoundError(
                f"Real-data model artifact not found at {REAL_ARTIFACT_PATH}. "
                "Run backend/scripts/train_real_dataset.py (Phase 3N) first."
            )
        log.info(f"Loading validated real-data XGBoost model from {REAL_ARTIFACT_PATH}...")
        _CACHED_MODEL = QuantileOutageModel.load(REAL_ARTIFACT_PATH)
    return _CACHED_MODEL


def get_calibration() -> dict:
    """Load (and cache) the Phase 3P calibration parameters."""
    global _CACHED_CALIBRATION
    if _CACHED_CALIBRATION is None:
        if not REAL_CALIBRATION_PATH.exists():
            raise FileNotFoundError(f"Calibration metadata not found at {REAL_CALIBRATION_PATH}")
        _CACHED_CALIBRATION = json.loads(REAL_CALIBRATION_PATH.read_text())
    return _CACHED_CALIBRATION


def _strip_mcc_footer(mcc_bytes: bytes) -> bytes:
    """MCC.csv's trailing 'Grand Total' row is an export artifact, not a
    county, and must not reach normalize_fips(). Same cleanup used by
    backend/scripts/build_multi_storm_dataset.py."""
    text = mcc_bytes.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    header, data_lines = lines[0], lines[1:]
    kept = [ln for ln in data_lines if ln.split(",", 1)[0].strip().isdigit()]
    return (header + "".join(kept)).encode("utf-8")


def get_static_tables() -> dict[str, Any]:
    """Load (and cache) the real county geometry + context source tables
    used for every live prediction: Census county centroids, FEMA NRI,
    CDC SVI, archive MCC customer counts, and the NOAA ONI table."""
    global _CACHED_STATIC_TABLES
    if _CACHED_STATIC_TABLES is None:
        log.info("Loading real county geometry + context source tables (first prediction only)...")
        if MCC_LOCAL_PATH.exists():
            mcc_bytes = MCC_LOCAL_PATH.read_bytes()
        else:
            from .dataset import read_zip_member_from_gcs
            mcc_bytes = read_zip_member_from_gcs("raw/census/EAGLE I/24237376.zip", "MCC.csv")
        _CACHED_STATIC_TABLES = {
            "centroids": load_county_centroids(CENSUS_SHP_PATH),
            "nri": load_nri_table(),
            "svi": load_svi_table(),
            "oni": load_oni_table(),
            "mcc": load_mcc_customers(io.BytesIO(_strip_mcc_footer(mcc_bytes))),
        }
    return _CACHED_STATIC_TABLES


_CACHED_DENOMINATORS: dict[str, int] | None = None


def get_customer_denominators() -> dict[str, int]:
    """Customers per county for converting a predicted % into a customer count: the EAGLE-I fall-2025
    county counts (MCC only where missing) -- the denominator of the training target, so predicted
    and actual outage counts are on the same footing. Not a model feature: customers_served_log
    stays MCC, exactly as in training."""
    global _CACHED_DENOMINATORS
    if _CACHED_DENOMINATORS is None:
        from .build_training_table import load_customers
        _CACHED_DENOMINATORS = load_customers()
    return _CACHED_DENOMINATORS


def get_name_lookup() -> dict[str, dict]:
    """Display-only name/state lookup (NOT a model feature source -- see
    live_inference.py / county_context_features.py for the real feature
    tables). dataset.load_county_static_lookup()'s own docstring documents
    this stub-safe-defaults behavior as intended for exactly this live-demo
    display use, distinct from the gap-revealing tables used for features."""
    global _CACHED_NAME_LOOKUP
    if _CACHED_NAME_LOOKUP is None:
        _CACHED_NAME_LOOKUP = load_county_static_lookup()
    return _CACHED_NAME_LOOKUP


def select_live_snapshot(forecast_points: list[ForecastPoint], lead_time_h: float) -> ForecastSnapshot:
    """Live-inference snapshot selection.

    Unlike atcf_forecast.select_leakage_safe_snapshot() (training/backtest
    only -- it requires a KNOWN impact_time_utc, which does not exist yet for
    an in-progress storm), this picks the forecast point at TAU==lead_time_h
    from the LATEST available advisory cycle, and uses that point's own
    valid_time_utc as the honest "when" anchor: the forecast's own prediction
    of conditions at that horizon, not a future ground truth no one has yet.
    """
    if not forecast_points:
        raise MissingForecastDataError("No ATCF forecast points supplied; cannot select a live snapshot.")

    latest_cycle = max(p.cycle_init_time_utc for p in forecast_points)
    same_cycle = [p for p in forecast_points if p.cycle_init_time_utc == latest_cycle]
    matches = [p for p in same_cycle if p.tau_h == int(lead_time_h)]
    if not matches:
        available = sorted({p.tau_h for p in same_cycle})
        raise MissingForecastDataError(
            f"No forecast point at tau_h={int(lead_time_h)} in the latest advisory cycle "
            f"({latest_cycle}); this cycle has tau values {available}. Request one of those, "
            "or supply a forecast that includes the requested lead time."
        )
    point = matches[0]
    return ForecastSnapshot(
        lead_time_h=lead_time_h,
        forecast_tau_h=point.tau_h,
        cycle_init_time_utc=point.cycle_init_time_utc,
        valid_time_utc=point.valid_time_utc,
        forecast=point,
    )


def _nearest_adjacent_point(forecast_points: list[ForecastPoint], point: ForecastPoint) -> ForecastPoint | None:
    """Another forecast point from the same cycle, for deriving forward speed
    when the ATCF SPEED field itself is absent. Never fabricated -- None if
    no other TAU exists in this cycle."""
    same_cycle_others = [
        p for p in forecast_points
        if p.cycle_init_time_utc == point.cycle_init_time_utc and p.tau_h != point.tau_h
    ]
    if not same_cycle_others:
        return None
    return min(same_cycle_others, key=lambda p: abs(p.tau_h - point.tau_h))


def run_impact_pipeline(
    county_fips: list[str] | None = None,
    advisory: dict[str, Any] | None = None,
    forecast_points: list[ForecastPoint] | None = None,
    lead_time_h: float | None = None,
) -> dict:
    """Execute the live impact-prediction pipeline using the validated
    real-data model and Phase 3P calibration.

    advisory carries only display/bookkeeping fields (storm_id, storm_name,
    advisory_number) -- it is NOT a source of model features. The genuine
    ATCF forecast geometry/intensity must come through forecast_points (a
    list of atcf_forecast.ForecastPoint, e.g. parsed from a real a-deck via
    atcf_forecast.load_atcf_forecasts()). If forecast_points is not supplied,
    this raises MissingForecastDataError rather than inventing a storm
    track/intensity -- the current demo advisory (backend/agent/stub_data.py
    ADVISORY) is free-text only and has no real track position, so it cannot
    honestly drive this path.
    """
    adv = advisory or {}
    if not forecast_points:
        raise MissingForecastDataError(
            "No real ATCF forecast data supplied (forecast_points is empty/None). The model's "
            "dist_to_track_nm, quadrant_right, and forward_speed_kt features require a genuine "
            "storm track position, heading, and speed from an ATCF a-deck forecast -- "
            "backend/agent/stub_data.py's ADVISORY has none of this (just free text like "
            "'Florida Big Bend coast'), so it cannot honestly drive real inference. Supply "
            "forecast_points from atcf_forecast.load_atcf_forecasts() against a real a-deck file."
        )

    lead = float(lead_time_h if lead_time_h is not None else adv.get("lead_time_to_landfall_h", 72.0))
    snapshot = select_live_snapshot(forecast_points, lead)
    adjacent = _nearest_adjacent_point(forecast_points, snapshot.forecast)

    fips_targets = county_fips or DEFAULT_FIPS_TARGETS
    static = get_static_tables()
    centroids = static["centroids"]
    name_lookup = get_name_lookup()

    storm_id = adv.get("storm_id", snapshot.forecast.storm_id)
    storm_name = adv.get("storm_name", snapshot.forecast.storm_name)

    rows = []
    for fips in fips_targets:
        fips_clean = normalize_fips(fips)
        match = centroids.loc[centroids["county_fips"] == fips_clean]
        if match.empty:
            raise MissingForecastDataError(
                f"County FIPS {fips_clean} has no entry in the Census county centroid table "
                f"({CENSUS_SHP_PATH.name}); cannot compute dist_to_track_nm/quadrant_right for it."
            )
        county_lat, county_lon = float(match.iloc[0]["county_lat"]), float(match.iloc[0]["county_lon"])

        row = build_live_feature_row(
            storm_id=storm_id,
            storm_name=storm_name,
            county_fips=fips_clean,
            county_lat=county_lat,
            county_lon=county_lon,
            snapshot=snapshot,
            nri_df=static["nri"],
            svi_df=static["svi"],
            mcc_df=static["mcc"],
            oni_df=static["oni"],
            adjacent_point=adjacent,
        )
        rows.append(row)

    # Step 1-2: construct the exact 13-feature rows, in FEATURE_COLUMNS order, and validate it.
    df = pd.DataFrame([r.to_feature_dict() for r in rows])
    df = df[FEATURE_COLUMNS]
    assert list(df.columns) == FEATURE_COLUMNS, "live feature frame drifted from schema.FEATURE_COLUMNS"

    # Step 3-4: run the validated real model; predict_quantiles() already clips to [0,100]
    # and enforces low<=median<=high on the RAW (uncalibrated) prediction.
    model = get_model()
    raw_quantiles = model.predict_quantiles(df)

    # Step 5-7: apply Phase 3P stratified-conformal calibration to q10/q90 only (median untouched),
    # clip to [0,100], and re-enforce ordering.
    calibration = get_calibration()
    calibrated: list[CalibratedInterval] = [
        apply_calibration(float(q[0]), float(q[1]), float(q[2]), calibration) for q in raw_quantiles
    ]

    counties_output = []
    for row, cal in zip(rows, calibrated):
        feats = row.to_feature_dict()
        name_info = name_lookup.get(row.county_fips, {"name": f"County {row.county_fips}", "state": "US"})

        risk_tier = QuantileOutageModel.assign_risk_tier(cal.median, feats["svi_overall"], feats["max_wind_kt"])
        # explain() only reads non-log-transformed display attributes (wind/distance/quadrant/tree/svi/
        # nri_risk_score/oni); constructing a minimal CountyFeatures here for that call alone is safe --
        # this object is never passed through features_to_dataframe()'s log1p transform.
        explain_cf = CountyFeatures(
            fips=row.county_fips, name=name_info["name"], state=name_info["state"],
            max_wind_kt=feats["max_wind_kt"], dist_to_track_nm=feats["dist_to_track_nm"],
            gust_wind_kt=feats["gust_wind_kt"], forward_speed_kt=feats["forward_speed_kt"],
            quadrant_right=int(feats["quadrant_right"]), tree_canopy_pct=feats["tree_canopy_pct"],
            nri_risk_score=feats["nri_risk_score"], svi_overall=feats["svi_overall"],
            oni_anomaly=feats["oni_anomaly"], lead_time_h=feats["lead_time_h"],
        )
        why = QuantileOutageModel.explain(explain_cf, cal.median)

        # The model input above is MCC (as in training); turning % into customers uses the target's own
        # EAGLE-I fall-2025 denominator, the same one the real outage records were divided by.
        customers_served = get_customer_denominators().get(row.county_fips) \
            or int(round(np.expm1(feats["customers_served_log"])))

        counties_output.append({
            "fips": row.county_fips,
            "name": name_info["name"],
            "state": name_info["state"],
            "risk_tier": risk_tier,
            "pct_customers_out": {"low": cal.low, "median": cal.median, "high": cal.high},
            "customers_served": customers_served,
            "why": why,
            "calibration_status": cal.calibration_status,
            "severe_uncertainty_caveat": cal.severe_uncertainty_caveat,
        })

    adv_num = int(adv.get("advisory_number", 0))
    return {
        "advisory_number": adv_num,
        "model_version": model.version,
        "counties": counties_output,
        "source": f"Quantile XGBoost Impact Model ({model.version}) + Phase 3P stratified-conformal "
                   "calibration, trained on EAGLE-I, HURDAT2, ATCF OFCL, FEMA NRI, CDC SVI, NOAA ONI",
        "data_source": "real_atcf_model",
        "forecast_cycle_utc": snapshot.cycle_init_time_utc.isoformat(),
        "forecast_valid_time_utc": snapshot.valid_time_utc.isoformat(),
        "requested_lead_time_h": snapshot.lead_time_h,
    }


def run_live_impact_pipeline(
    storm_query: str,
    county_fips: list[str] | None = None,
    lead_time_h: float = 72.0,
    basin: str = "AL",
    advisory_number: int | None = None,
) -> dict:
    """Phase 3R: fetch the CURRENT official NHC ATCF forecast for `storm_query`
    (an ATCF id like "AL052024" or a storm name like "MILTON") and run it
    through run_impact_pipeline().

    Raises (never silently falls back -- that decision belongs to the
    caller, e.g. agent/tools.py's existing try/except around predict_impact):
      - live_atcf_source.AtcfNetworkError on a network failure
      - live_atcf_source.NoActiveStormError if no matching active storm
      - live_atcf_source.MalformedAtcfResponseError on a malformed response
      - live_atcf_source.NoOfclForecastError if no OFCL points are present
      - MissingForecastDataError if the requested lead_time_h's TAU isn't in
        the latest advisory cycle, or a requested county has no geometry
      - live_inference.UnresolvedLiveFeatureError if a county's real feature
        data has a gap
    """
    from .live_atcf_source import get_live_ofcl_forecast

    points, storm = get_live_ofcl_forecast(storm_query, basin=basin)
    advisory = {
        "storm_id": storm.atcf_id,
        "storm_name": storm.name,
        "advisory_number": advisory_number if advisory_number is not None else 0,
    }
    return run_impact_pipeline(
        county_fips=county_fips, advisory=advisory, forecast_points=points, lead_time_h=lead_time_h,
    )


def run_scenario_impact_pipeline(
    county_fips: list[str] | None = None,
    lead_time_h: float = 72.0,
    scenario=None,
    advisory_number: int | None = None,
) -> dict:
    """Run a deterministic synthetic scenario (scenario_generator.py) through
    the EXACT same real inference path real/live forecasts use -- same
    feature engineering, same trained model, same Phase 3P calibration.
    This is NOT a second inference implementation: it calls
    run_impact_pipeline() unmodified, exactly like run_live_impact_pipeline()
    does. Only the ForecastPoint SOURCE differs (synthetic, not a real
    a-deck), and only the result's data_source/source labels are overridden
    afterward, so callers (and the frontend) can never confuse this with a
    live NHC-driven result.
    """
    from .scenario_generator import FLORIDA_GULF_COAST_SCENARIO, generate_scenario_forecast_points

    cfg = scenario or FLORIDA_GULF_COAST_SCENARIO
    points = generate_scenario_forecast_points(cfg)
    advisory = {
        "storm_id": points[0].storm_id if points else None,
        "storm_name": cfg.storm_name,
        "advisory_number": advisory_number if advisory_number is not None else 0,
    }
    result = run_impact_pipeline(
        county_fips=county_fips, advisory=advisory, forecast_points=points, lead_time_h=lead_time_h,
    )
    result["data_source"] = "scenario_model"
    result["source"] = f"SIMULATED SCENARIO ({cfg.storm_name}, not a real storm) -- " + result["source"]
    return result
