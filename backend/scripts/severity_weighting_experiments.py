"""Phase 3O: focused severe-outage model improvement experiments.

Re-runs the exact Phase 3N leave-one-storm-out (LOSO) procedure 3 times --
baseline (unweighted, reproducing Phase 3N), a continuous severity-weighted
fit, and a band-based imbalance-correction weighted fit -- using the same
4,749 rows, 13 FEATURE_COLUMNS, target, LOSO folds, and QuantileOutageModel
architecture as Phase 3N. The only thing that changes between experiments is
the per-row sample_weight passed into QuantileOutageModel.fit().

Does not touch pipeline.py/API/frontend/agents, does not add features/storms,
does not change target construction, does not run a broad hyperparameter
search, and does not overwrite the Phase 3N artifact
(outage_xgb_real_v1.joblib). Only writes a new artifact if a weighted variant
is recommended at the end.
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
from backend.scripts.train_real_dataset import (
    CANONICAL_GCS_PATH,
    SEVERITY_BANDS,
    EXPECTED_STORMS,
    _fold_metrics,
    _raw_quantile_predictions,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "models" / "artifacts"
PHASE_3N_ARTIFACT = DEFAULT_OUTPUT_DIR / "outage_xgb_real_v1.joblib"

# --- Weighting schemes -------------------------------------------------------
# Both are simple, monotonic in severity, and deliberately capped so no row
# gets an extreme weight relative to the rest of the batch.


def weight_none(df: pd.DataFrame) -> None:
    """Baseline: no weighting, reproduces Phase 3N exactly."""
    return None


def weight_linear_severity(df: pd.DataFrame, k: float = 25.0) -> np.ndarray:
    """Continuous severity weighting: w(y) = 1 + y/k.

    At y=0%, w=1 (no change from baseline). At y=100%, w=1+100/25=5, i.e. a
    severe row counts 5x as much as a zero-outage row during fitting. Simple,
    monotonic in the target, bounded to a 5x max ratio -- not extreme.
    """
    y = df["pct_customers_out"].to_numpy(dtype=float)
    return 1.0 + y / k


def weight_band_sqrt_freq(df: pd.DataFrame) -> np.ndarray:
    """Band imbalance-correction weighting: sqrt-inverse-frequency per
    severity band, normalized so the largest (most common) band keeps weight
    ~1.0. This is the standard "soften, don't fully invert" class-imbalance
    trick -- full inverse frequency would hit ~7.4x for the smallest band,
    sqrt damps that to ~2.7x, a moderate, non-extreme correction.

    Band counts (fixed, computed once from the full 4,749-row dataset so the
    same row always gets the same weight regardless of which storm is held
    out that fold):
        0-5%:    3018 rows
        5-20%:    681 rows
        20-40%:   408 rows
        40-100%:  642 rows
    """
    y = df["pct_customers_out"].to_numpy(dtype=float)
    band_edges = [(lo, hi) for _, lo, hi in SEVERITY_BANDS]
    n_total = len(df)
    band_counts = []
    for lo, hi in band_edges:
        band_counts.append(int(((df["pct_customers_out"] >= lo) & (df["pct_customers_out"] < hi)).sum()))
    raw_weights = [np.sqrt(n_total / c) for c in band_counts]
    min_w = min(raw_weights)
    norm_weights = [w / min_w for w in raw_weights]  # largest band -> 1.0

    weights = np.ones(len(y), dtype=float)
    for (lo, hi), w in zip(band_edges, norm_weights):
        mask = (y >= lo) & (y < hi)
        weights[mask] = w
    return weights


EXPERIMENTS = {
    "A_baseline_unweighted": weight_none,
    "B_linear_severity_weight": weight_linear_severity,
    "C_band_sqrt_freq_weight": weight_band_sqrt_freq,
}


def run_loso_cv_weighted(df: pd.DataFrame, weight_fn) -> tuple[pd.DataFrame, dict]:
    """Same LOSO procedure as train_real_dataset.run_loso_cv, parameterized by
    a sample-weighting function applied to each fold's training rows only
    (never to the held-out test rows, which are always evaluated unweighted)."""
    storms_present = set(df["storm_name"].unique())
    if storms_present != EXPECTED_STORMS:
        log.warning(f"Storm set mismatch: present={sorted(storms_present)} expected={sorted(EXPECTED_STORMS)}")

    oof_rows = []
    per_storm_metrics = {}

    for train_df, test_df, storm in leave_one_storm_out(df):
        X_train, y_train = train_df[FEATURE_COLUMNS], train_df["pct_customers_out"]
        X_test, y_test = test_df[FEATURE_COLUMNS], test_df["pct_customers_out"].to_numpy(dtype=float)
        sample_weight = weight_fn(train_df)

        model = QuantileOutageModel(alpha_low=0.10, alpha_median=0.50, alpha_high=0.90)
        model.fit(X_train, y_train, sample_weight=sample_weight)

        quantiles = model.predict_quantiles(X_test)
        raw = _raw_quantile_predictions(model, X_test)

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

    q10_gt_q50 = int((oof_df["raw_low"] > oof_df["raw_med"]).sum())
    q50_gt_q90 = int((oof_df["raw_med"] > oof_df["raw_high"]).sum())

    report = {
        "per_storm": per_storm_metrics,
        "aggregate": aggregate,
        "by_horizon": by_horizon_agg,
        "by_severity_band": by_severity_agg,
        "quantile_violations_raw": {"q10_gt_q50": q10_gt_q50, "q50_gt_q90": q50_gt_q90, "total_rows": int(len(oof_df))},
        "actual_mean": round(float(oof_df["y_true"].mean()), 3),
        "predicted_median_mean": round(float(oof_df["pred_med"].mean()), 3),
    }
    return oof_df, report


def print_comparison_table(all_reports: dict[str, dict]) -> None:
    log.info("\n=== Comparison table (aggregate across all 6 OOF folds) ===")
    header = f"{'Experiment':<28}{'MAE':>8}{'RMSE':>8}{'Cov%':>8}{'Width':>8}{'ActMean':>9}{'PredMean':>10}"
    log.info(header)
    for name, report in all_reports.items():
        agg = report["aggregate"]
        log.info(
            f"{name:<28}{agg['mae_median']:>8.2f}{agg['rmse_median']:>8.2f}{agg['coverage_pct']:>8.1f}"
            f"{agg['mean_interval_width']:>8.2f}{report['actual_mean']:>9.2f}{report['predicted_median_mean']:>10.2f}"
        )

    log.info("\n=== 40-100% severity band (the critical regime) ===")
    header2 = f"{'Experiment':<28}{'n':>6}{'MAE':>8}{'RMSE':>8}{'Cov%':>8}{'Width':>8}"
    log.info(header2)
    for name, report in all_reports.items():
        band = report["by_severity_band"].get("40-100%", {})
        log.info(
            f"{name:<28}{band.get('n', 0):>6}{band.get('mae_median', float('nan')):>8.2f}"
            f"{band.get('rmse_median', float('nan')):>8.2f}{band.get('coverage_pct', float('nan')):>8.1f}"
            f"{band.get('mean_interval_width', float('nan')):>8.2f}"
        )

    log.info("\n=== Low-severity bands (checking for unacceptable cost) ===")
    for band_name in ["0-5%", "5-20%"]:
        log.info(f"-- {band_name} --")
        for name, report in all_reports.items():
            band = report["by_severity_band"].get(band_name, {})
            log.info(
                f"{name:<28} n={band.get('n', 0):<6} MAE={band.get('mae_median', float('nan')):<8.2f} "
                f"Cov%={band.get('coverage_pct', float('nan')):<6.1f}"
            )


def main():
    parser = argparse.ArgumentParser(description="Phase 3O: severity-weighting LOSO experiments")
    parser.add_argument("--data", type=str, default=CANONICAL_GCS_PATH)
    parser.add_argument("--save-variant", type=str, default=None, choices=list(EXPERIMENTS.keys()),
                         help="If set, also fit this variant on all rows and save as a new versioned artifact.")
    parser.add_argument("--artifact-name", type=str, default="outage_xgb_real_v2_severity_weighted")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    log.info(f"Loading real training dataset from: {args.data}")
    df = load_training_dataframe(args.data)
    log.info(f"Loaded {len(df)} rows, storms={sorted(df['storm_name'].unique())}")

    all_reports = {}
    for name, weight_fn in EXPERIMENTS.items():
        log.info(f"\n### Running LOSO experiment: {name} ###")
        oof_df, report = run_loso_cv_weighted(df, weight_fn)
        all_reports[name] = report
        log.info(f"[{name}] aggregate: {json.dumps(report['aggregate'])}")
        log.info(f"[{name}] 40-100% band: {json.dumps(report['by_severity_band'].get('40-100%', {}))}")
        log.info(f"[{name}] actual_mean={report['actual_mean']} predicted_median_mean={report['predicted_median_mean']}")
        log.info(f"[{name}] per_storm: {json.dumps({k: {kk: vv for kk, vv in v.items() if kk != 'by_horizon'} for k, v in report['per_storm'].items()}, indent=2)}")
        log.info(f"[{name}] by_horizon: {json.dumps(report['by_horizon'], indent=2)}")

    print_comparison_table(all_reports)

    if args.save_variant:
        log.info(f"\n=== Fitting recommended variant '{args.save_variant}' on all rows and saving new artifact ===")
        weight_fn = EXPERIMENTS[args.save_variant]
        sample_weight = weight_fn(df)
        final_model = QuantileOutageModel(
            alpha_low=0.10, alpha_median=0.50, alpha_high=0.90,
            version="xgboost-quantile-real-v2-severity-weighted",
        )
        final_model.fit(df[FEATURE_COLUMNS], df["pct_customers_out"], sample_weight=sample_weight)

        args.output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = args.output_dir / f"{args.artifact_name}.joblib"
        metadata_path = args.output_dir / f"{args.artifact_name}.meta.json"
        if artifact_path == PHASE_3N_ARTIFACT:
            raise RuntimeError("Refusing to overwrite the Phase 3N artifact -- choose a different --artifact-name.")
        final_model.save(artifact_path)

        metadata = {
            "artifact_name": args.artifact_name,
            "model_version": final_model.version,
            "trained_at_utc": datetime.now(timezone.utc).isoformat(),
            "phase": "3O",
            "based_on": "outage_xgb_real_v1 (Phase 3N)",
            "weighting_scheme": args.save_variant,
            "training_dataset": {
                "canonical_gcs_path": CANONICAL_GCS_PATH,
                "actual_load_path_used": str(args.data),
                "n_storms": int(df["storm_name"].nunique()),
                "storms": sorted(df["storm_name"].unique()),
                "n_rows": int(len(df)),
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
            "validation_strategy": "leave-one-storm-out (LOSO) across 6 real storms, same as Phase 3N",
            "validation_summary_for_this_weighting_scheme": all_reports[args.save_variant],
            "validation_summary_baseline_for_comparison": all_reports["A_baseline_unweighted"],
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, default=str))
        log.info(f"Saved new artifact to: {artifact_path}")
        log.info(f"Saved metadata to: {metadata_path}")

    return all_reports


if __name__ == "__main__":
    main()
