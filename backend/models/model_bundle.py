"""A named, versioned model bundle: artifact + feature schema + calibration + metadata, loaded
and used together so the backend is never ambiguous about which joblib/metadata/calibration
belong to which other. Adapted from xgboost-pred's live_inference.py (Phase 3P calibration) onto
current main's unmodified QuantileOutageModel/CountyFeatures (the two branches share the exact
same save/load bundle format and FEATURE_COLUMNS, so no model-code change was needed to load the
new artifact -- see backend/models/schema.py).

Bundle name "outage_xgb_real_v1" is the real, LOSO-validated artifact trained on 6 real storms
(see artifacts/outage_xgb_real_v1.meta.json). It is unrelated to the older artifacts/
outage_xgb_v1.joblib used by the single-agent stub pipeline (models/pipeline.py) -- the two are
never mixed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .outage_model import QuantileOutageModel
from .schema import FEATURE_COLUMNS, CountyFeatures

log = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
GCS_BUNDLE_PREFIX = "processed/hurricane/models/bundles"  # gs://<bucket>/<prefix>/<name>/<name>.*


class ModelBundleUnavailable(RuntimeError):
    """Raised when a named bundle's artifact/metadata/calibration can't all be loaded, or its
    metadata's feature schema doesn't match this code's CountyFeatures/FEATURE_COLUMNS. Never
    caught to silently substitute a different bundle, an older artifact, or synthetic output --
    callers must report this as a model/data-unavailable state."""


# Validation found below-nominal interval coverage in these predicted-severity bands even after
# calibration (outage_xgb_real_v1_calibration.json's loso_validation_summary). Carried over from
# xgboost-pred's live_inference.py so callers never present these as a reliable bound.
SEVERE_UNCERTAINTY_CAVEATS: dict[str, str] = {
    "40-100%": ("Validation (leave-one-storm-out) found only ~27% empirical coverage for the most "
                "severe outages even after calibration. Treat this interval as a rough, experimental "
                "bound for this high-impact county, not a reliable uncertainty estimate."),
    "20-40%": ("Validation found below-nominal (~54% vs. an 80% target) interval coverage in this "
               "band. Treat this uncertainty interval as indicative, not precise."),
}


def select_predicted_band(pred_med: float, pred_bands: list[dict]) -> str:
    """Which band the model's OWN predicted median falls into -- the only thing observable at
    inference time (never an unknown true outcome)."""
    for band in pred_bands:
        if band["lo"] <= pred_med < band["hi"]:
            return band["label"]
    return pred_bands[-1]["label"]


@dataclass(frozen=True)
class CalibratedQuantile:
    low: float
    median: float
    high: float
    predicted_band: str
    calibration_status: str  # "stratified_conformal" | "stratified_conformal_global_fallback"
    q_applied: float
    severe_uncertainty_caveat: str | None


def apply_calibration(pred_low: float, pred_med: float, pred_high: float, calibration: dict) -> CalibratedQuantile:
    """Phase 3P stratified-conformal correction: low_cal = clip(low - Q, 0, med),
    high_cal = clip(high + Q, med, 100), where Q is the calibration pool's correction for the
    model's own predicted band (falling back to the global Q when that band's pool was too
    small). Median is never modified. Adapted near-verbatim from xgboost-pred's
    live_inference.py:apply_calibration."""
    band = select_predicted_band(pred_med, calibration["pred_bands"])
    q_by_band = calibration.get("Q_by_band") or {}
    if band in q_by_band:
        q, status = q_by_band[band], "stratified_conformal"
    else:
        q, status = calibration["Q_global"], "stratified_conformal_global_fallback"

    cal_low, cal_high = pred_low - q, pred_high + q
    cal_low, cal_high = min(cal_low, cal_high), max(cal_low, cal_high)
    cal_low = max(0.0, min(cal_low, pred_med))
    cal_high = min(100.0, max(cal_high, pred_med))
    return CalibratedQuantile(low=round(cal_low, 1), median=round(pred_med, 1), high=round(cal_high, 1),
                              predicted_band=band, calibration_status=status, q_applied=round(float(q), 3),
                              severe_uncertainty_caveat=SEVERE_UNCERTAINTY_CAVEATS.get(band))


def _validate_feature_schema(name: str, meta: dict) -> None:
    cols = meta.get("feature_columns")
    if cols != FEATURE_COLUMNS:
        raise ModelBundleUnavailable(
            f"bundle {name!r} feature_columns {cols!r} does not match this code's FEATURE_COLUMNS "
            f"{FEATURE_COLUMNS!r} -- refusing to use a model with a mismatched feature schema/order."
        )


def _local_paths(name: str) -> tuple[Path, Path, Path] | None:
    joblib_p, meta_p, cal_p = (ARTIFACTS_DIR / f"{name}.joblib", ARTIFACTS_DIR / f"{name}.meta.json",
                               ARTIFACTS_DIR / f"{name}_calibration.json")
    return (joblib_p, meta_p, cal_p) if joblib_p.exists() and meta_p.exists() and cal_p.exists() else None


def _load_from_gcs(name: str) -> tuple[QuantileOutageModel, dict, dict]:
    import os
    import tempfile

    from google.cloud import storage

    bucket_name = os.getenv("STORM_DATA_BUCKET", "uc3-storm-impact-intelligence-data")
    bucket = storage.Client().bucket(bucket_name)
    prefix = f"{GCS_BUNDLE_PREFIX}/{name}/{name}"
    with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as f:
        bucket.blob(f"{prefix}.joblib").download_to_filename(f.name)
        model = QuantileOutageModel.load(f.name)
    meta = json.loads(bucket.blob(f"{prefix}.meta.json").download_as_bytes())
    calibration = json.loads(bucket.blob(f"{prefix}_calibration.json").download_as_bytes())
    return model, meta, calibration


@dataclass(frozen=True)
class ModelBundle:
    """One named, versioned model: the fitted QuantileOutageModel, its metadata (feature
    columns, LOSO validation summary) and its calibration, loaded and used together."""

    name: str
    model: QuantileOutageModel
    meta: dict
    calibration: dict

    @property
    def model_version(self) -> str:
        return self.meta.get("model_version", self.model.version)

    @property
    def skill_summary(self) -> dict:
        """Held-out model skill for the ImpactEstimate contract's model_skill field: median
        error from the LOSO validation, and coverage AFTER calibration (the number that
        actually describes what the UI shows), not the raw pre-calibration coverage."""
        agg = self.meta.get("validation_summary", {}).get("aggregate", {})
        cal_agg = self.calibration.get("loso_validation_summary", {}).get("aggregate", {})
        return {
            "mae_median": agg.get("mae_median"),
            "coverage_pct": cal_agg.get("coverage_pct", agg.get("coverage_pct")),
            "tested_on": self.meta.get("validation_strategy", "leave-one-storm-out validation"),
        }

    @property
    def source(self) -> str:
        td = self.meta.get("training_dataset", {})
        storms = ", ".join(td.get("storms", [])) or "?"
        return (f"Quantile XGBoost outage model {self.model_version} (bundle {self.name}), trained on "
                f"{td.get('n_rows', '?')} storm-county rows from {td.get('n_storms', '?')} real storms "
                f"({storms}), EAGLE-I labels, stratified-conformal calibrated")

    def predict_one(self, features: CountyFeatures) -> dict:
        """One county's calibrated prediction, contract-shaped (fips/name/state/risk_tier/
        pct_customers_out/customers_served/why) plus calibration/model provenance fields."""
        raw = self.model.predict([features], source_note=self.source)
        county = raw["counties"][0]
        q = county["pct_customers_out"]
        cal = apply_calibration(q["low"], q["median"], q["high"], self.calibration)
        county["pct_customers_out"] = {"low": cal.low, "median": cal.median, "high": cal.high}
        # Risk tier from the CALIBRATED median -- what the UI actually shows -- not the raw one.
        county["risk_tier"] = QuantileOutageModel.assign_risk_tier(cal.median, features.svi_overall, features.max_wind_kt)
        county["calibration"] = {
            "status": cal.calibration_status, "predicted_band": cal.predicted_band,
            "q_applied": cal.q_applied, "severe_uncertainty_caveat": cal.severe_uncertainty_caveat,
        }
        county["model_version"] = self.model_version
        county["model_bundle"] = self.name
        return county


@lru_cache(maxsize=4)
def load_bundle(name: str) -> ModelBundle:
    """Load a named bundle (joblib + .meta.json + _calibration.json) local-first (backend/
    models/artifacts/<name>.*), then GCS under gs://<bucket>/processed/hurricane/models/bundles/
    <name>/<name>.* -- the explicit bundle-selection mechanism: a bundle name always resolves to
    one matched artifact+metadata+calibration triple, never a silently-swapped single file.
    Raises ModelBundleUnavailable (never falls back to a different bundle or synthetic output)."""
    try:
        local = _local_paths(name)
        if local:
            joblib_p, meta_p, cal_p = local
            model = QuantileOutageModel.load(joblib_p)
            meta = json.loads(meta_p.read_text())
            calibration = json.loads(cal_p.read_text())
        else:
            model, meta, calibration = _load_from_gcs(name)
    except ModelBundleUnavailable:
        raise
    except Exception as e:
        raise ModelBundleUnavailable(f"model bundle {name!r} unavailable: {e}") from e

    _validate_feature_schema(name, meta)
    return ModelBundle(name=name, model=model, meta=meta, calibration=calibration)
