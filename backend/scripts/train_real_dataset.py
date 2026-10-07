"""Phase 3N: leave-one-storm-out cross-validation and final training of
QuantileOutageModel on the real multi-storm processed dataset.

Loads the canonical real dataset (never silently substituting synthetic
bootstrap data -- see train.load_training_dataframe), evaluates the existing
QuantileOutageModel with storm-aware leave-one-storm-out (LOSO) validation
across the 6 real storms, reports diagnostics (per-storm, per-horizon,
aggregate, quantile-violation, feature-importance), and -- if the results
look reasonable for the MVP -- fits one final model on all rows and saves a
versioned artifact alongside a JSON metadata sidecar.

Does not redesign the model, tune hyperparameters, add features, change
target construction, touch pipeline.py, or integrate with the API/frontend.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from backend.models.schema import FEATURE_COLUMNS
from backend.models.outage_model import QuantileOutageModel
from backend.models.split import leave_one_storm_out
from backend.models.train import load_training_dataframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

CANONICAL_GCS_PATH = (
    "gs://uc3-storm-impact-intelligence-data/processed/training/multi_storm_2018_2024/training_rows.csv"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "models" / "artifacts"
EXPECTED_STORMS = {"FLORENCE", "MICHAEL", "IAN", "IDALIA", "HELENE", "MILTON"}
SEVERITY_BANDS = [
    ("0-5%", 0.0, 5.0),
    ("5-20%", 5.0, 20.0),
    ("20-40%", 20.0, 40.0),
    ("40-100%", 40.0, 100.0 + 1e-9),
]


def _raw_quantile_predictions(model: QuantileOutageModel, X: pd.DataFrame) -> np.ndarray:
    """Raw, un-clipped, un-reordered [low, med, high] predictions straight from
    the three underlying XGBRegressors -- used only for quantile-violation
    diagnostics. Production predictions always go through predict_quantiles(),
    which clips to [0,100] and enforces low<=med<=high."""
    X_mat = X[FEATURE_COLUMNS].to_numpy()
    raw_low = model.model_low.predict(X_mat)
    raw_med = model.model_median.predict(X_mat)
    raw_high = model.model_high.predict(X_mat)
    return np.column_stack([raw_low, raw_med, raw_high])


def _fold_metrics(y_true: np.ndarray, low: np.ndarray, med: np.ndarray, high: np.ndarray) -> dict:
    mae = float(np.mean(np.abs(y_true - med)))
    rmse = float(np.sqrt(np.mean((y_true - med) ** 2)))
    coverage = float(np.mean((y_true >= low) & (y_true <= high)) * 100.0)
    width = float(np.mean(high - low))
    return {
        "n": int(len(y_true)),
        "mae_median": round(mae, 3),
        "rmse_median": round(rmse, 3),
        "coverage_pct": round(coverage, 1),
        "mean_interval_width": round(width, 3),
    }


def run_loso_cv(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Leave-one-storm-out CV. Returns (oof_predictions_df, report_dict)."""
    storms_present = set(df["storm_name"].unique())
    if storms_present != EXPECTED_STORMS:
        log.warning(f"Storm set mismatch: present={sorted(storms_present)} expected={sorted(EXPECTED_STORMS)}")

    oof_rows = []
    per_storm_metrics = {}

    for train_df, test_df, storm in leave_one_storm_out(df):
        X_train, y_train = train_df[FEATURE_COLUMNS], train_df["pct_customers_out"]
        X_test, y_test = test_df[FEATURE_COLUMNS], test_df["pct_customers_out"].to_numpy(dtype=float)

        model = QuantileOutageModel(alpha_low=0.10, alpha_median=0.50, alpha_high=0.90)
        model.fit(X_train, y_train)

        quantiles = model.predict_quantiles(X_test)  # production path: clipped + reordered
        raw = _raw_quantile_predictions(model, X_test)  # diagnostic path: unmodified

        fold_df = pd.DataFrame({
            "storm_name": storm,
            "county_fips": test_df["county_fips"].to_numpy(),
            "lead_time_h": test_df["lead_time_h"].to_numpy(),
            "y_true": y_test,
            "pred_low": quantiles[:, 0],
            "pred_med": quantiles[:, 1],
            "pred_high": quantiles[:, 2],
            "raw_low": raw[:, 0],
            "raw_med": raw[:, 1],
            "raw_high": raw[:, 2],
        })
        oof_rows.append(fold_df)

        fold_metrics = _fold_metrics(y_test, quantiles[:, 0], quantiles[:, 1], quantiles[:, 2])
        by_horizon = {}
        for h in sorted(test_df["lead_time_h"].unique(), reverse=True):
            mask = (test_df["lead_time_h"] == h).to_numpy()
            by_horizon[str(int(h))] = _fold_metrics(
                y_test[mask], quantiles[mask, 0], quantiles[mask, 1], quantiles[mask, 2]
            )
        per_storm_metrics[storm] = {**fold_metrics, "by_horizon": by_horizon}

        log.info(
            f"[LOSO held-out={storm}] n={fold_metrics['n']} "
            f"MAE={fold_metrics['mae_median']} RMSE={fold_metrics['rmse_median']} "
            f"coverage={fold_metrics['coverage_pct']}% width={fold_metrics['mean_interval_width']}"
        )

    oof_df = pd.concat(oof_rows, ignore_index=True)

    aggregate = _fold_metrics(
        oof_df["y_true"].to_numpy(), oof_df["pred_low"].to_numpy(),
        oof_df["pred_med"].to_numpy(), oof_df["pred_high"].to_numpy(),
    )
    by_horizon_agg = {}
    for h in sorted(oof_df["lead_time_h"].unique(), reverse=True):
        mask = oof_df["lead_time_h"] == h
        sub = oof_df[mask]
        by_horizon_agg[str(int(h))] = _fold_metrics(
            sub["y_true"].to_numpy(), sub["pred_low"].to_numpy(), sub["pred_med"].to_numpy(), sub["pred_high"].to_numpy()
        )

    by_severity_agg = {}
    for label, lo, hi in SEVERITY_BANDS:
        mask = (oof_df["y_true"] >= lo) & (oof_df["y_true"] < hi)
        sub = oof_df[mask]
        if len(sub) > 0:
            by_severity_agg[label] = _fold_metrics(
                sub["y_true"].to_numpy(), sub["pred_low"].to_numpy(), sub["pred_med"].to_numpy(), sub["pred_high"].to_numpy()
            )

    # Quantile-order violations on the RAW (pre-clip, pre-reorder) model outputs --
    # shows how often the three independently-trained quantile heads would have
    # crossed if predict_quantiles() did not enforce monotonicity.
    q10_gt_q50 = int((oof_df["raw_low"] > oof_df["raw_med"]).sum())
    q50_gt_q90 = int((oof_df["raw_med"] > oof_df["raw_high"]).sum())
    # Confirm production path (predict_quantiles) never violates monotonicity.
    prod_q10_gt_q50 = int((oof_df["pred_low"] > oof_df["pred_med"]).sum())
    prod_q50_gt_q90 = int((oof_df["pred_med"] > oof_df["pred_high"]).sum())

    report = {
        "per_storm": per_storm_metrics,
        "aggregate": aggregate,
        "by_horizon": by_horizon_agg,
        "by_severity_band": by_severity_agg,
        "quantile_violations": {
            "raw_q10_gt_q50": q10_gt_q50,
            "raw_q50_gt_q90": q50_gt_q90,
            "raw_total_rows": int(len(oof_df)),
            "production_q10_gt_q50_after_enforcement": prod_q10_gt_q50,
            "production_q50_gt_q90_after_enforcement": prod_q50_gt_q90,
        },
        "actual_vs_predicted_summary": {
            "y_true": oof_df["y_true"].describe().round(3).to_dict(),
            "pred_med": oof_df["pred_med"].describe().round(3).to_dict(),
        },
    }
    return oof_df, report


def feature_importance_report(model: QuantileOutageModel) -> dict:
    """Default XGBoost feature_importances_ (gain-based, sklearn API default)
    for each of the 3 quantile heads. Reported for diagnostic visibility only --
    not a substitute for SHAP/permutation importance, and not to be over-read
    given only 6 storms / 4,749 rows."""
    report = {}
    for head_name, head_model in [("q10", model.model_low), ("q50", model.model_median), ("q90", model.model_high)]:
        importances = head_model.feature_importances_
        report[head_name] = {
            col: round(float(imp), 4)
            for col, imp in sorted(zip(FEATURE_COLUMNS, importances), key=lambda kv: -kv[1])
        }
    return report


def main():
    parser = argparse.ArgumentParser(description="Phase 3N: LOSO-CV and final training on the real multi-storm dataset")
    parser.add_argument("--data", type=str, default=CANONICAL_GCS_PATH, help="gs:// URI or local path to training_rows.csv")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory to save the final artifact + metadata")
    parser.add_argument("--artifact-name", type=str, default="outage_xgb_real_v1", help="Base filename (no extension) for the final artifact")
    parser.add_argument("--report-json", type=Path, default=None, help="Optional path to also dump the full LOSO report as JSON")
    args = parser.parse_args()

    log.info(f"Loading real training dataset from: {args.data}")
    df = load_training_dataframe(args.data)
    log.info(f"Loaded {len(df)} rows, {df['county_fips'].nunique()} unique counties, storms={sorted(df['storm_name'].unique())}")

    log.info("=== Running leave-one-storm-out (LOSO) cross-validation across 6 storms ===")
    oof_df, report = run_loso_cv(df)

    log.info("=== Aggregate out-of-fold metrics (all 6 held-out folds combined) ===")
    log.info(json.dumps(report["aggregate"], indent=2))
    log.info("=== Per-horizon aggregate metrics ===")
    log.info(json.dumps(report["by_horizon"], indent=2))
    log.info("=== Per-severity-band aggregate metrics ===")
    log.info(json.dumps(report["by_severity_band"], indent=2))
    log.info("=== Quantile violation diagnostics ===")
    log.info(json.dumps(report["quantile_violations"], indent=2))

    log.info("=== Fitting final model on all rows (no held-out split) ===")
    final_model = QuantileOutageModel(
        alpha_low=0.10, alpha_median=0.50, alpha_high=0.90,
        version="xgboost-quantile-real-v1.0",
    )
    X_all, y_all = df[FEATURE_COLUMNS], df["pct_customers_out"]
    final_model.fit(X_all, y_all)

    importance_report = feature_importance_report(final_model)
    log.info("=== Feature importance (final model, default XGBoost feature_importances_) ===")
    log.info(json.dumps(importance_report, indent=2))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = args.output_dir / f"{args.artifact_name}.joblib"
    metadata_path = args.output_dir / f"{args.artifact_name}.meta.json"

    final_model.save(artifact_path)

    metadata = {
        "artifact_name": args.artifact_name,
        "model_version": final_model.version,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "training_dataset": {
            "canonical_gcs_path": CANONICAL_GCS_PATH,
            "actual_load_path_used": str(args.data),
            "n_storms": int(df["storm_name"].nunique()),
            "storms": sorted(df["storm_name"].unique()),
            "n_rows": int(len(df)),
            "n_unique_counties": int(df["county_fips"].nunique()),
        },
        "feature_columns": FEATURE_COLUMNS,
        "model_params": {
            "alpha_low": final_model.alpha_low,
            "alpha_median": final_model.alpha_median,
            "alpha_high": final_model.alpha_high,
            "n_estimators": final_model.model_median.get_params()["n_estimators"],
            "max_depth": final_model.model_median.get_params()["max_depth"],
            "learning_rate": final_model.model_median.get_params()["learning_rate"],
            "random_state": final_model.model_median.get_params()["random_state"],
            "objective": final_model.model_median.get_params()["objective"],
            "xgboost_version": xgb.__version__,
        },
        "validation_strategy": "leave-one-storm-out (LOSO) across 6 real storms: "
                                 "Florence 2018, Michael 2018, Ian 2022, Idalia 2023, Helene 2024, Milton 2024",
        "validation_summary": {
            "aggregate": report["aggregate"],
            "by_horizon": report["by_horizon"],
            "by_severity_band": report["by_severity_band"],
            "per_storm": {k: {kk: vv for kk, vv in v.items() if kk != "by_horizon"} for k, v in report["per_storm"].items()},
            "quantile_violations": report["quantile_violations"],
        },
        "feature_importance": importance_report,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2))

    log.info(f"Final model saved to: {artifact_path}")
    log.info(f"Metadata saved to: {metadata_path}")

    if args.report_json:
        args.report_json.write_text(json.dumps(report, indent=2, default=str))
        log.info(f"Full LOSO report saved to: {args.report_json}")

    return report, metadata


if __name__ == "__main__":
    main()
