"""Runtime access to hurricane county packs and the trained impact model.

Packs: data/processed/packs/hurricane/<fips>/ locally, else gs://<bucket>/processed/packs/hurricane/<fips>/.
Model: gs://<bucket>/processed/hurricane/models/<HURRICANE_MODEL_RUN>/outage_xgb_real.joblib (+ run.json).
No silent fallback: a missing pack raises; a missing model is reported by the tool as an error.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)
LOCAL = Path(__file__).resolve().parents[2] / "data" / "processed" / "packs" / "hurricane"
BUCKET = os.getenv("STORM_DATA_BUCKET", "uc3-storm-impact-intelligence-data")
FILES = ("pack.json", "storms.json", "assets.json", "geo.geojson", "replay.json")


class PackUnavailable(RuntimeError):
    pass


def _blob(path: str):
    from google.cloud import storage
    return storage.Client().bucket(BUCKET).blob(path)


def _read_json(rel: str):
    local = LOCAL / rel
    if local.exists():
        return json.loads(local.read_text())
    try:
        return json.loads(_blob(f"processed/packs/hurricane/{rel}").download_as_bytes())
    except Exception as e:
        raise PackUnavailable(f"hurricane pack file {rel} not found locally ({local}) or in "
                              f"gs://{BUCKET}/processed/packs/hurricane: {e}. Run `python -m hurricane.build_pack`.") from e


@lru_cache(maxsize=None)
def index() -> list[dict]:
    return _read_json("index.json")


@lru_cache(maxsize=None)
def table(fips: str, name: str):
    if name not in FILES:
        raise KeyError(name)
    return _read_json(f"{fips}/{name}")


def pack(fips: str) -> dict:
    return table(fips, "pack.json")


def load_all(fips: str) -> dict:
    return {n: table(fips, n) for n in FILES}


@lru_cache(maxsize=1)
def model():
    """(QuantileOutageModel, run.json) for HURRICANE_MODEL_RUN. Raises if unset or missing."""
    run = os.getenv("HURRICANE_MODEL_RUN", "").strip()
    if not run:
        raise RuntimeError("HURRICANE_MODEL_RUN is not set (e.g. real-20261005-1851)")
    from models.outage_model import QuantileOutageModel
    prefix = f"processed/hurricane/models/{run}"
    with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as f:
        _blob(f"{prefix}/outage_xgb_real.joblib").download_to_filename(f.name)
        m = QuantileOutageModel.load(f.name)
    meta = json.loads(_blob(f"{prefix}/run.json").download_as_bytes())
    log.info("hurricane model %s loaded (%s rows, %s storms)", run, meta.get("rows"), meta.get("storms"))
    return m, meta
