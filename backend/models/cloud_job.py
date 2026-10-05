"""Vertex AI custom job entrypoint: build the real training table, then train on it.

    python -m models.cloud_job --stage all   --run-id 20261005-1
    python -m models.cloud_job --stage table --run-id ...
    python -m models.cloud_job --stage train --run-id ... [--table gs://.../training_table.csv]

Outputs (gs://uc3-storm-impact-intelligence-data/processed/hurricane/):
  training_table.csv + training_table_manifest.json
  models/<run_id>/outage_xgb_real.joblib, metrics_temporal.json, metrics_storm.json, run.json

No synthetic fallback: train.py falls back to the bootstrap generator when its path doesn't exist, so this
runner checks the table exists and has enough rows first, then passes the gs:// path (which raises on failure).
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone

import pandas as pd

from .dataset import DEFAULT_GCS_BUCKET, get_gcs_blob_bytes
from .train import train_and_save

log = logging.getLogger(__name__)
PREFIX = f"gs://{DEFAULT_GCS_BUCKET}/processed/hurricane"
TABLE = f"{PREFIX}/training_table.csv"
MIN_ROWS = 300
TRAIN_END_YEAR = 2021   # temporal split: train <= this, test after; recorded in run.json


def upload(local: str, gs: str) -> None:
    from google.cloud import storage
    bucket, blob = gs[5:].split("/", 1)
    storage.Client().bucket(bucket).blob(blob).upload_from_filename(local)
    log.info("uploaded %s -> %s", local, gs)


def put_json(obj, gs: str) -> None:
    from google.cloud import storage
    bucket, blob = gs[5:].split("/", 1)
    storage.Client().bucket(bucket).blob(blob).upload_from_string(json.dumps(obj, indent=1, default=str),
                                                                  content_type="application/json")


def stage_table(years: str) -> None:
    cmd = [sys.executable, "-m", "models.build_training_table", "--out", TABLE, "--years", years]
    log.info("running %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def stage_train(table: str, run_id: str) -> None:
    df = pd.read_csv(io.BytesIO(get_gcs_blob_bytes(table)))
    if len(df) < MIN_ROWS or "pct_customers_out" not in df.columns:
        raise SystemExit(f"{table}: {len(df)} rows / columns {list(df.columns)[:6]}... - refusing to train")
    out = f"{PREFIX}/models/{run_id}"
    runs = {}
    # Temporal split (train <= TRAIN_END_YEAR, test after) is the artifact we keep; the held-out-storm split
    # (Idalia, Hilary, Michael, Ian) is a second, harder check reported alongside it.
    for split in ("storm", "temporal"):
        path = f"/tmp/outage_xgb_real_{split}.joblib"
        _, metrics = train_and_save(data_path=table, output_path=path, split_strategy=split,
                                    train_end_year=TRAIN_END_YEAR, test_start_year=TRAIN_END_YEAR + 1)
        runs[split] = metrics
        put_json(metrics, f"{out}/metrics_{split}.json")
    upload("/tmp/outage_xgb_real_temporal.joblib", f"{out}/outage_xgb_real.joblib")
    put_json({"run_id": run_id, "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "table": table, "rows": len(df), "storms": int(df["storm_id"].nunique()),
              "years": sorted(int(y) for y in df["year"].unique()), "artifact_split": "temporal",
              "train_end_year": TRAIN_END_YEAR,
              "metrics": runs, "git_commit": os.getenv("GIT_COMMIT", "unknown")}, f"{out}/run.json")
    log.info("done: %s", out)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["table", "train", "all"], default="all")
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--years", default="2014-2025")
    ap.add_argument("--table", default=TABLE)
    a = ap.parse_args()
    if a.stage in ("table", "all"):
        stage_table(a.years)
    if a.stage in ("train", "all"):
        stage_train(a.table, a.run_id)


if __name__ == "__main__":
    main()
