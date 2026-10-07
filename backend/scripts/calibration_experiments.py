"""Phase 3P: leakage-safe post-hoc interval calibration for QuantileOutageModel.

Keeps the existing median prediction and base XGBoost architecture exactly as
trained in Phase 3N/3O; only the q10/q90 INTERVAL is adjusted post-hoc using
split-conformal-style residual calibration (Romano et al. 2019, "Conformalized
Quantile Regression"), evaluated with the same 6-storm leave-one-storm-out
(LOSO) procedure.

Leakage safety: for each outer held-out storm S, calibration parameters are
derived ONLY from the other 5 ("training-side") storms, via a NESTED
leave-one-storm-out within those 5 storms. Each calibration residual therefore
comes from a model that never saw that residual's own storm -- and none of
them ever saw S. The outer model (trained on all 5 training storms) is only
ever applied to, never calibrated on, S.

Two narrow approaches are tested, both built on the same conformal residual:
  1. Global conformal calibration -- one additive correction Q applied to
     every row's [low, high] interval.
  2. Predicted-severity-stratified ("Mondrian") conformal calibration -- a
     separate correction Q_band per band of the model's OWN predicted
     median (not the unknown true outcome -- this is observable at
     application time, so it stays leakage-safe), falling back to the global
     Q when a band's calibration pool is too small (< MIN_STRATUM_N) to
     trust its own quantile estimate.

No feature/storm/target changes, no retraining of the feature pipeline, no
changes to pipeline.py/API/frontend/agents, and the Phase 3N artifact is
never overwritten -- this script only reads data and writes new, separate
calibration metadata if a method proves useful.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from backend.models.schema import FEATURE_COLUMNS
from backend.models.outage_model import QuantileOutageModel
from backend.models.split import leave_one_storm_out
from backend.models.train import load_training_dataframe
from backend.scripts.train_real_dataset import CANONICAL_GCS_PATH, SEVERITY_BANDS, EXPECTED_STORMS, _fold_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "models" / "artifacts"

ALPHA = 0.20  # nominal miscoverage for the q10-q90 interval (target: 80% coverage)
MIN_STRATUM_N = 20  # minimum calibration-pool rows per predicted-severity band before trusting its own Q
PRED_BANDS = SEVERITY_BANDS  # reuse the exact same 4 band edges, applied here to the model's OWN predicted median


def conformal_quantile(scores: np.ndarray, alpha: float = ALPHA) -> float:
    """Finite-sample-corrected (1-alpha) empirical quantile of nonconformity
    scores (split-conformal / CQR calibration, Romano et al. 2019)."""
    n = len(scores)
    if n == 0:
        return 0.0
    level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def nonconformity_scores(y_true: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """How far y_true falls outside [low, high]; <=0 means inside the interval."""
    return np.maximum(low - y_true, y_true - high)


def apply_global_calibration(low: np.ndarray, high: np.ndarray, Q: float) -> tuple[np.ndarray, np.ndarray]:
    cal_low = low - Q
    cal_high = high + Q
    cal_low, cal_high = np.minimum(cal_low, cal_high), np.maximum(cal_low, cal_high)
    return np.clip(cal_low, 0.0, 100.0), np.clip(cal_high, 0.0, 100.0)


def apply_stratified_calibration(
    low: np.ndarray, high: np.ndarray, pred_med: np.ndarray,
    Q_by_band: dict[str, float], Q_global: float,
) -> tuple[np.ndarray, np.ndarray]:
    cal_low = low.copy()
    cal_high = high.copy()
    assigned = np.zeros(len(low), dtype=bool)
    for label, lo_b, hi_b in PRED_BANDS:
        mask = (pred_med >= lo_b) & (pred_med < hi_b)
        Q = Q_by_band.get(label, Q_global)
        cal_low[mask] = low[mask] - Q
        cal_high[mask] = high[mask] + Q
        assigned |= mask
    if not assigned.all():  # bands cover [0,100] so this shouldn't fire; safety net only
        m = ~assigned
        cal_low[m] = low[m] - Q_global
        cal_high[m] = high[m] + Q_global
    cal_low, cal_high = np.minimum(cal_low, cal_high), np.maximum(cal_low, cal_high)
    return np.clip(cal_low, 0.0, 100.0), np.clip(cal_high, 0.0, 100.0)


def inner_oof_calibration_pool(train_df: pd.DataFrame) -> pd.DataFrame:
    """Nested LOSO within the 5 training-side storms: each inner storm is
    predicted by a model trained on the OTHER 4 training storms only, so every
    calibration residual comes from a model that never saw that row's storm --
    and, by construction, none of these inner models ever see the outer
    held-out storm either."""
    rows = []
    for inner_train, inner_test, _inner_storm in leave_one_storm_out(train_df):
        model = QuantileOutageModel(alpha_low=0.10, alpha_median=0.50, alpha_high=0.90)
        model.fit(inner_train[FEATURE_COLUMNS], inner_train["pct_customers_out"])
        q = model.predict_quantiles(inner_test[FEATURE_COLUMNS])
        rows.append(pd.DataFrame({
            "y_true": inner_test["pct_customers_out"].to_numpy(dtype=float),
            "pred_low": q[:, 0], "pred_med": q[:, 1], "pred_high": q[:, 2],
        }))
    return pd.concat(rows, ignore_index=True)


def run_all_approaches(df: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict]:
    """Single LOSO pass producing OOF predictions for all 3 approaches
    (uncalibrated / global_conformal / stratified_conformal) at once, so the
    outer model and the calibration pool are computed exactly once per fold
    and shared -- guaranteeing an apples-to-apples comparison."""
    oof_rows = {"uncalibrated": [], "global_conformal": [], "stratified_conformal": []}
    fold_diagnostics = {}

    for train_df, test_df, storm in leave_one_storm_out(df):
        outer_model = QuantileOutageModel(alpha_low=0.10, alpha_median=0.50, alpha_high=0.90)
        outer_model.fit(train_df[FEATURE_COLUMNS], train_df["pct_customers_out"])
        q = outer_model.predict_quantiles(test_df[FEATURE_COLUMNS])
        low, med, high = q[:, 0], q[:, 1], q[:, 2]
        y_true = test_df["pct_customers_out"].to_numpy(dtype=float)
        lead_time_h = test_df["lead_time_h"].to_numpy()

        cal_pool = inner_oof_calibration_pool(train_df)
        scores = nonconformity_scores(
            cal_pool["y_true"].to_numpy(), cal_pool["pred_low"].to_numpy(), cal_pool["pred_high"].to_numpy()
        )
        Q_global = conformal_quantile(scores)

        Q_by_band, band_n = {}, {}
        for label, lo_b, hi_b in PRED_BANDS:
            mask = ((cal_pool["pred_med"] >= lo_b) & (cal_pool["pred_med"] < hi_b)).to_numpy()
            band_n[label] = int(mask.sum())
            if band_n[label] >= MIN_STRATUM_N:
                Q_by_band[label] = conformal_quantile(scores[mask])

        glob_low, glob_high = apply_global_calibration(low, high, Q_global)
        strat_low, strat_high = apply_stratified_calibration(low, high, med, Q_by_band, Q_global)

        fold_diagnostics[storm] = {
            "n_calibration_pool": int(len(cal_pool)),
            "Q_global": round(Q_global, 3),
            "Q_by_band": {k: round(v, 3) for k, v in Q_by_band.items()},
            "band_calibration_pool_n": band_n,
            "bands_using_global_fallback": [label for label, _, _ in PRED_BANDS if label not in Q_by_band],
        }

        base = {"storm_name": storm, "lead_time_h": lead_time_h, "y_true": y_true, "pred_med": med}
        oof_rows["uncalibrated"].append(pd.DataFrame({**base, "cal_low": low, "cal_high": high}))
        oof_rows["global_conformal"].append(pd.DataFrame({**base, "cal_low": glob_low, "cal_high": glob_high}))
        oof_rows["stratified_conformal"].append(pd.DataFrame({**base, "cal_low": strat_low, "cal_high": strat_high}))

        log.info(
            f"[{storm}] cal_pool_n={len(cal_pool)} Q_global={Q_global:.2f} "
            f"Q_by_band={{{', '.join(f'{k}:{v:.2f}' for k, v in Q_by_band.items())}}} "
            f"(fallback to global for: {fold_diagnostics[storm]['bands_using_global_fallback']})"
        )

    oof_dfs = {name: pd.concat(rows, ignore_index=True) for name, rows in oof_rows.items()}
    return oof_dfs, fold_diagnostics


def build_report(oof_df: pd.DataFrame) -> dict:
    aggregate = _fold_metrics(
        oof_df["y_true"].to_numpy(), oof_df["cal_low"].to_numpy(), oof_df["pred_med"].to_numpy(), oof_df["cal_high"].to_numpy()
    )
    by_storm = {}
    for storm in sorted(oof_df["storm_name"].unique()):
        sub = oof_df[oof_df["storm_name"] == storm]
        by_storm[storm] = _fold_metrics(
            sub["y_true"].to_numpy(), sub["cal_low"].to_numpy(), sub["pred_med"].to_numpy(), sub["cal_high"].to_numpy()
        )
    by_horizon = {}
    for h in sorted(oof_df["lead_time_h"].unique(), reverse=True):
        sub = oof_df[oof_df["lead_time_h"] == h]
        by_horizon[str(int(h))] = _fold_metrics(
            sub["y_true"].to_numpy(), sub["cal_low"].to_numpy(), sub["pred_med"].to_numpy(), sub["cal_high"].to_numpy()
        )
    by_severity = {}
    for label, lo, hi in SEVERITY_BANDS:
        mask = (oof_df["y_true"] >= lo) & (oof_df["y_true"] < hi)
        sub = oof_df[mask]
        if len(sub) > 0:
            by_severity[label] = _fold_metrics(
                sub["y_true"].to_numpy(), sub["cal_low"].to_numpy(), sub["pred_med"].to_numpy(), sub["cal_high"].to_numpy()
            )
    return {"aggregate": aggregate, "by_storm": by_storm, "by_horizon": by_horizon, "by_severity_band": by_severity}


def print_comparison(reports: dict[str, dict]) -> None:
    log.info("\n=== Aggregate comparison (all 4,749 OOF rows) ===")
    log.info(f"{'Approach':<22}{'MAE':>7}{'RMSE':>7}{'Cov%':>7}{'Width':>8}")
    for name, rep in reports.items():
        a = rep["aggregate"]
        log.info(f"{name:<22}{a['mae_median']:>7.2f}{a['rmse_median']:>7.2f}{a['coverage_pct']:>7.1f}{a['mean_interval_width']:>8.2f}")

    log.info("\n=== 40-100% severe band ===")
    log.info(f"{'Approach':<22}{'n':>5}{'Cov%':>7}{'Width':>8}{'WidthExpansion':>16}")
    base_width = reports["uncalibrated"]["by_severity_band"].get("40-100%", {}).get("mean_interval_width", float("nan"))
    for name, rep in reports.items():
        b = rep["by_severity_band"].get("40-100%", {})
        expansion = b.get("mean_interval_width", float("nan")) / base_width if base_width else float("nan")
        log.info(f"{name:<22}{b.get('n', 0):>5}{b.get('coverage_pct', float('nan')):>7.1f}{b.get('mean_interval_width', float('nan')):>8.2f}{expansion:>16.2f}x")

    log.info("\n=== All severity bands: coverage% / width (checking for uniform-widening vs targeted improvement) ===")
    for label, _, _ in SEVERITY_BANDS:
        log.info(f"-- {label} --")
        for name, rep in reports.items():
            b = rep["by_severity_band"].get(label, {})
            log.info(f"   {name:<22} n={b.get('n',0):<6} Cov%={b.get('coverage_pct', float('nan')):<6.1f} Width={b.get('mean_interval_width', float('nan')):<7.2f}")

    log.info("\n=== By horizon ===")
    for h in ["72", "48", "24"]:
        log.info(f"-- {h}h --")
        for name, rep in reports.items():
            b = rep["by_horizon"].get(h, {})
            log.info(f"   {name:<22} Cov%={b.get('coverage_pct', float('nan')):<6.1f} Width={b.get('mean_interval_width', float('nan')):<7.2f}")

    log.info("\n=== By storm ===")
    for storm in sorted(EXPECTED_STORMS):
        log.info(f"-- {storm} --")
        for name, rep in reports.items():
            b = rep["by_storm"].get(storm, {})
            log.info(f"   {name:<22} Cov%={b.get('coverage_pct', float('nan')):<6.1f} Width={b.get('mean_interval_width', float('nan')):<7.2f}")


def main():
    parser = argparse.ArgumentParser(description="Phase 3P: leakage-safe post-hoc interval calibration experiments")
    parser.add_argument("--data", type=str, default=CANONICAL_GCS_PATH)
    parser.add_argument("--save-approach", type=str, default=None, choices=["global_conformal", "stratified_conformal"],
                         help="If set, derive final calibration parameters from all 6 storms (nested LOSO pool) and save as metadata alongside outage_xgb_real_v1 (never overwriting the model itself).")
    parser.add_argument("--calibration-name", type=str, default="outage_xgb_real_v1_calibration")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    log.info(f"Loading real training dataset from: {args.data}")
    df = load_training_dataframe(args.data)
    log.info(f"Loaded {len(df)} rows, storms={sorted(df['storm_name'].unique())}")

    oof_dfs, fold_diagnostics = run_all_approaches(df)
    reports = {name: build_report(oof_df) for name, oof_df in oof_dfs.items()}
    print_comparison(reports)

    if args.save_approach:
        log.info(f"\n=== Deriving final calibration parameters for '{args.save_approach}' (full-data nested-LOSO pool) ===")
        # Leakage-safe for FUTURE inference: every residual still comes from a model
        # that excluded that row's own storm (standard leave-one-storm-out pool across
        # all 6 real storms), never from the final production model itself.
        cal_pool = inner_oof_calibration_pool(df)
        scores = nonconformity_scores(cal_pool["y_true"].to_numpy(), cal_pool["pred_low"].to_numpy(), cal_pool["pred_high"].to_numpy())
        Q_global = conformal_quantile(scores)
        Q_by_band, band_n = {}, {}
        for label, lo_b, hi_b in PRED_BANDS:
            mask = ((cal_pool["pred_med"] >= lo_b) & (cal_pool["pred_med"] < hi_b)).to_numpy()
            band_n[label] = int(mask.sum())
            if band_n[label] >= MIN_STRATUM_N:
                Q_by_band[label] = conformal_quantile(scores[mask])

        args.output_dir.mkdir(parents=True, exist_ok=True)
        calibration_path = args.output_dir / f"{args.calibration_name}.json"
        calibration = {
            "calibration_name": args.calibration_name,
            "base_model_artifact": "outage_xgb_real_v1.joblib",
            "phase": "3P",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "approach": args.save_approach,
            "alpha": ALPHA,
            "min_stratum_n": MIN_STRATUM_N,
            "Q_global": round(Q_global, 3),
            "Q_by_band": {k: round(v, 3) for k, v in Q_by_band.items()} if args.save_approach == "stratified_conformal" else None,
            "band_calibration_pool_n": band_n if args.save_approach == "stratified_conformal" else None,
            "pred_bands": [{"label": l, "lo": lo, "hi": hi} for l, lo, hi in PRED_BANDS],
            "application_formula": (
                "low_cal = clip(low - Q, 0, 100); high_cal = clip(high + Q, 0, 100); "
                "then sort so low_cal <= high_cal. For stratified_conformal, Q is Q_by_band[band(pred_med)] "
                "falling back to Q_global when that band's calibration pool was < min_stratum_n."
            ),
            "loso_validation_summary": reports[args.save_approach],
            "loso_baseline_for_comparison": reports["uncalibrated"],
        }
        calibration_path.write_text(json.dumps(calibration, indent=2, default=str))
        log.info(f"Saved calibration parameters/metadata to: {calibration_path}")
        log.info("Base model artifact outage_xgb_real_v1.joblib was NOT modified.")

    return reports, fold_diagnostics


if __name__ == "__main__":
    main()
