"""Training script for Quantile XGBoost Outage Impact Model.

Trains low (0.10), median (0.50), and high (0.90) quantile models,
evaluates performance against simple baselines, and saves the trained bundle.
"""

from __future__ import annotations
import argparse
import logging
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .schema import FEATURE_COLUMNS
from .outage_model import QuantileOutageModel
from .synthetic_bootstrap import generate_bootstrap_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_ARTIFACT_PATH = Path(__file__).parent / "artifacts" / "outage_xgb_v1.joblib"


def evaluate_model(
    model: QuantileOutageModel,
    X_test: pd.DataFrame,
    y_test: pd.Series | np.ndarray,
) -> dict:
    """Evaluate quantile accuracy, interval coverage, and baseline comparison."""
    y_true = np.asarray(y_test, dtype=float)
    quantiles = model.predict_quantiles(X_test)
    pred_low, pred_med, pred_high = quantiles[:, 0], quantiles[:, 1], quantiles[:, 2]

    mae_median = float(np.mean(np.abs(y_true - pred_med)))
    coverage = float(np.mean((y_true >= pred_low) & (y_true <= pred_high)) * 100.0)

    # Baseline: Simple wind-only threshold rule (as specified in proposal §10)
    baseline_pred = np.clip((X_test["max_wind_kt"] - 30.0) * 1.2, 0.0, 100.0)
    baseline_mae = float(np.mean(np.abs(y_true - baseline_pred)))

    metrics = {
        "mae_median": round(mae_median, 2),
        "coverage_pct": round(coverage, 1),
        "baseline_mae": round(baseline_mae, 2),
        "improvement_over_baseline_pct": round(max(0, (baseline_mae - mae_median) / baseline_mae * 100.0), 1),
    }
    return metrics


def train_and_save(
    data_path: str | Path | None = None,
    output_path: Path = DEFAULT_ARTIFACT_PATH,
    n_samples: int = 2000,
) -> tuple[QuantileOutageModel, dict]:
    """Train quantile outage model and save artifact."""
    if data_path:
        str_path = str(data_path)
        if str_path.startswith("gs://"):
            from .dataset import get_gcs_blob_bytes
            import io
            log.info(f"Loading training dataset directly from Google Cloud Storage: {str_path}...")
            raw_bytes = get_gcs_blob_bytes(str_path)
            buf = io.BytesIO(raw_bytes)
            if str_path.endswith(".parquet"):
                df = pd.read_parquet(buf)
            else:
                df = pd.read_csv(buf)
            X = df[FEATURE_COLUMNS]
            y = df["pct_customers_out"]
        elif Path(data_path).exists():
            path_obj = Path(data_path)
            log.info(f"Loading real training dataset from local file {path_obj}...")
            if path_obj.suffix == ".parquet":
                df = pd.read_parquet(path_obj)
            else:
                df = pd.read_csv(path_obj)
            X = df[FEATURE_COLUMNS]
            y = df["pct_customers_out"]
        else:
            log.warning(f"Specified path {data_path} not found. Falling back to calibrated bootstrap dataset.")
            X, y = generate_bootstrap_dataset(n_samples=n_samples, random_seed=42)
    else:
        log.info(f"Upstream ETL in progress: generating calibrated bootstrap dataset ({n_samples} samples)...")
        X, y = generate_bootstrap_dataset(n_samples=n_samples, random_seed=42)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    log.info(f"Training Quantile XGBoost (low={0.10}, median={0.50}, high={0.90}) on {len(X_train)} samples...")
    model = QuantileOutageModel(alpha_low=0.10, alpha_median=0.50, alpha_high=0.90)
    model.fit(X_train, y_train)

    metrics = evaluate_model(model, X_test, y_test)
    log.info(f"Evaluation Results:")
    log.info(f"  • Median MAE: {metrics['mae_median']}% customers out")
    log.info(f"  • Interval Coverage [q10, q90]: {metrics['coverage_pct']}%")
    log.info(f"  • Baseline MAE: {metrics['baseline_mae']}%")
    log.info(f"  • Improvement over baseline: {metrics['improvement_over_baseline_pct']}%")

    model.save(output_path)
    log.info(f"Model saved successfully to {output_path}")
    return model, metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Quantile XGBoost Outage Impact Model")
    parser.add_argument("--data", type=str, default=None, help="Path or gs:// URI to training data (parquet or csv)")
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_PATH, help="Path to save artifact")
    args = parser.parse_args()

    train_and_save(data_path=args.data, output_path=args.output)
