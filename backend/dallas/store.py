"""Runtime access to the processed Dallas tables (built by dallas.build).

Reads data/processed/dallas/ locally, else gs://<bucket>/processed/dallas/.
No silent fallback: if neither has the tables, the first call raises, so a
deploy without data fails at startup instead of serving empty answers.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

LOCAL = Path(__file__).resolve().parents[2] / "data" / "processed" / "dallas"
BUCKET = os.getenv("STORM_DATA_BUCKET", "uc3-storm-impact-intelligence-data")
FILES = ("storms.json", "assets.json", "districts.geojson", "climate.json", "manifest.json")


class DataUnavailable(RuntimeError):
    pass


def _read(name: str) -> dict | list:
    local = LOCAL / name
    if local.exists():
        return json.loads(local.read_text())
    try:
        from google.cloud import storage
        blob = storage.Client().bucket(BUCKET).blob(f"processed/dallas/{name}")
        log.info("loading gs://%s/processed/dallas/%s", BUCKET, name)
        return json.loads(blob.download_as_bytes())
    except Exception as e:
        raise DataUnavailable(
            f"Dallas table {name} not found locally ({local}) or in gs://{BUCKET}/processed/dallas: {e}. "
            "Run `python -m dallas.build` from backend/ (after pulling raw data) or check bucket access."
        ) from e


@lru_cache(maxsize=None)
def table(name: str):
    if name not in FILES:
        raise KeyError(name)
    return _read(name)


def storms() -> list[dict]:
    return table("storms.json")


def storm(storm_id: str) -> dict | None:
    return next((s for s in storms() if s["id"] == storm_id), None)


def assets() -> dict:
    return table("assets.json")


def districts() -> dict:
    return table("districts.geojson")


def climate() -> dict:
    return table("climate.json")


def manifest() -> dict:
    return table("manifest.json")


def load_all() -> dict:
    """Load every table now (call at app startup to fail fast)."""
    return {name: table(name) for name in FILES}
