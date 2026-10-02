"""Training script for Quantile XGBoost Outage Impact Model.

Supports rigorous validation without data leakage:
- Temporal period split (e.g. Train: 2014-2021, Test: 2022-2024)
- Held-out storm split (Idalia 2023, Hilary 2023, Michael 2018, Ian 2022)
Trains low (0.10), median (0.50), and high (0.90) quantile models,
evaluates performance against simple baselines, and saves the trained bundle.
"""

from __future__ import annotations
import argparse
import io
import logging
from pathlib import Path
from typing import Literal
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .schema import FEATURE_COLUMNS
from .outage_model import QuantileOutageModel
from .synthetic_bootstrap import generate_bootstrap_dataset
from .split import temporal_period_split, held_out_storm_split, DEFAULT_HELD_OUT_STORMS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_ARTIFACT_PATH = Path(__file__).parent / "artifacts" / "outage_xgb_v1.joblib"


def evaluate_model(
    model: QuantileOutageModel,
    df_test: pd.DataFrame,
    y_test: pd.Series | np.ndarray,
) -> dict:
    """Evaluate quantile accuracy, interval coverage, hardest-hit recall, and baseline comparison."""
    y_true = np.asarray(y_test, dtype=float)
    X_test = df_test[FEATURE_COLUMNS]
    quantiles = model.predict_quantiles(X_test)
    pred_low, pred_med, pred_high = quantiles[:, 0], quantiles[:, 1], quantiles[:, 2]

    mae_median = float(np.mean(np.abs(y_true - pred_med)))
    coverage = float(np.mean((y_true >= pred_low) & (y_true <= pred_high)) * 100.0)

    # Baseline: Simple wind-only threshold rule (as specified in proposal §10)
    baseline_pred = np.clip((X_test["max_wind_kt"] - 30.0) * 1.2, 0.0, 100.0)
    baseline_mae = float(np.mean(np.abs(y_true - baseline_pred)))

    # Hardest-hit county recall (counties with >= 40% outage predicted as red/orange >= 20%)
    hardest_hit_mask = y_true >= 40.0
    if np.any(hardest_hit_mask):
        recall_hardest_hit = float(np.mean(pred_med[hardest_hit_mask] >= 20.0) * 100.0)
    else:
        recall_hardest_hit = 100.0

    metrics = {
        "mae_median": round(mae_median, 2),
        "coverage_pct": round(coverage, 1),
        "recall_hardest_hit_pct": round(recall_hardest_hit, 1),
        "baseline_mae": round(baseline_mae, 2),
        "improvement_over_baseline_pct": round(max(0, (baseline_mae - mae_median) / baseline_mae * 100.0), 1),
    }

    # Per-storm breakdown if storm_name is present
    if "storm_name" in df_test.columns:
        per_storm = {}
        for storm in sorted(df_test["storm_name"].unique()):
            s_mask = (df_test["storm_name"] == storm).to_numpy()
            if np.any(s_mask):
                s_mae = float(np.mean(np.abs(y_true[s_mask] - pred_med[s_mask])))
                per_storm[storm] = round(s_mae, 2)
        metrics["per_storm_mae"] = per_storm

    return metrics


def train_and_save(
    data_path: str | Path | None = None,
    output_path: Path = DEFAULT_ARTIFACT_PATH,
    split_strategy: Literal["temporal", "storm", "random"] = "temporal",
    train_end_year: int = 2021,
    test_start_year: int = 2022,
    held_out_storms: list[str] | None = None,
    n_samples: int = 2500,
) -> tuple[QuantileOutageModel, dict]:
    """Train quantile outage model using period or storm-based splitting, and save artifact."""
    if data_path:
        str_path = str(data_path)
        if str_path.startswith("gs://"):
            from .dataset import get_gcs_blob_bytes
            log.info(f"Loading training dataset directly from Google Cloud Storage: {str_path}...")
            raw_bytes = get_gcs_blob_bytes(str_path)
            buf = io.BytesIO(raw_bytes)
            if str_path.endswith(".parquet"):
                df = pd.read_parquet(buf)
            else:
                df = pd.read_csv(buf)
        elif Path(data_path).exists():
            path_obj = Path(data_path)
            log.info(f"Loading real training dataset from local file {path_obj}...")
            if path_obj.suffix == ".parquet":
                df = pd.read_parquet(path_obj)
            else:
                df = pd.read_csv(path_obj)
        else:
            log.warning(f"Specified path {data_path} not found. Falling back to calibrated bootstrap dataset.")
            df, y = generate_bootstrap_dataset(n_samples=n_samples, random_seed=42)
            df["pct_customers_out"] = y
    else:
        log.info(f"Upstream ETL in progress: generating calibrated bootstrap dataset ({n_samples} samples)...")
        df, y = generate_bootstrap_dataset(n_samples=n_samples, random_seed=42)
        df["pct_customers_out"] = y

    # Validation Splitting Strategy
    if split_strategy == "temporal" and "year" in df.columns:
        log.info(f"Executing Temporal Period Split (Train: <= {train_end_year}, Test: >= {test_start_year})...")
        df_train, df_test = temporal_period_split(df, train_end_year, test_start_year)
    elif split_strategy == "storm" and "storm_name" in df.columns:
        test_storms = held_out_storms or DEFAULT_HELD_OUT_STORMS
        log.info(f"Executing Held-Out Storm Split (Test storms: {test_storms})...")
        df_train, df_test = held_out_storm_split(df, test_storms)
    else:
        log.info("Executing standard random split (fallback)...")
        df_train, df_test = train_test_split(df, test_size=0.2, random_state=42)

    X_train = df_train[FEATURE_COLUMNS]
    y_train = df_train["pct_customers_out"]
    X_test = df_test[FEATURE_COLUMNS]
    y_test = df_test["pct_customers_out"]

    log.info(f"Training Quantile XGBoost (low=0.10, median=0.50, high=0.90) on {len(X_train)} samples...")
    model = QuantileOutageModel(alpha_low=0.10, alpha_median=0.50, alpha_high=0.90)
    model.fit(X_train, y_train)

    metrics = evaluate_model(model, df_test, y_test)
    log.info(f"Evaluation Results ({split_strategy} split):")
    log.info(f"  • Median MAE: {metrics['mae_median']}% customers out")
    log.info(f"  • Interval Coverage [q10, q90]: {metrics['coverage_pct']}%")
    log.info(f"  • Hardest-Hit Recall (outages >= 40%): {metrics['recall_hardest_hit_pct']}%")
    log.info(f"  • Baseline MAE: {metrics['baseline_mae']}%")
    log.info(f"  • Improvement over baseline: {metrics['improvement_over_baseline_pct']}%")
    if "per_storm_mae" in metrics:
        log.info(f"  • Per-Storm MAE Breakdown:")
        for storm, s_mae in metrics["per_storm_mae"].items():
            log.info(f"      - {storm}: {s_mae}% MAE")

    model.save(output_path)
    log.info(f"Model saved successfully to {output_path}")
    return model, metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Quantile XGBoost Outage Impact Model")
    parser.add_argument("--data", type=str, default=None, help="Path or gs:// URI to training data")
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_PATH, help="Path to save artifact")
    parser.add_argument("--split", choices=["temporal", "storm", "random"], default="temporal",
                        help="Data splitting strategy (default: temporal period split)")
    parser.add_argument("--train-end-year", type=int, default=2021, help="Last year for training period")
    parser.add_argument("--test-start-year", type=int, default=2022, help="First year for test period")
    args = parser.parse_args()

    train_and_save(
        data_path=args.data,
        output_path=args.output,
        split_strategy=args.split,
        train_end_year=args.train_end_year,
        test_start_year=args.test_start_year,
    )
