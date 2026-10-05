"""Draft packs: local data/processed/packs_draft/ first, else gs://<bucket>/processed/packs_draft/.
Read-only for the API; writing happens in research.run (drafts) and research.publish (packs)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from research.schema import DraftPack, Verdict

log = logging.getLogger(__name__)
LOCAL = Path(__file__).resolve().parents[2] / "data" / "processed" / "packs_draft"
PREFIX = "processed/packs_draft/"
RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")


def _bucket():
    from google.cloud import storage
    from hurricane.store import BUCKET
    return storage.Client().bucket(BUCKET)


def _summary(d: DraftPack, source: str) -> dict:
    counts = {v.value: 0 for v in Verdict}
    for r in d.reviews:
        counts[r.verdict.value] += 1
    return {"run_id": d.run_id, "fips": d.target.fips, "county": d.target.county, "state": d.target.state,
            "hazard": d.target.hazard, "built_utc": d.built_utc, "facts": len(d.facts), "gaps": len(d.gaps),
            "reviewed": len(d.reviews), "verdicts": counts, "researcher_model": d.researcher_model,
            "judge_model": d.judge_model, "partial": bool(d.run_log.get("cap_hit")), "stored": source}


def list_drafts() -> list[dict]:
    out: dict[tuple, dict] = {}
    for p in sorted(LOCAL.glob("*/*/*.json")):
        try:
            d = DraftPack.model_validate_json(p.read_text())
            out[(d.target.fips, d.run_id)] = _summary(d, "local")
        except Exception as e:  # a bad file is listed as broken, not hidden
            log.error("draft %s unreadable: %s", p, e)
            out[(p.parent.name, p.stem)] = {"run_id": p.stem, "fips": p.parent.name, "error": str(e)}
    try:
        for blob in _bucket().list_blobs(prefix=PREFIX):
            hazard, fips, name = blob.name[len(PREFIX):].split("/")[-3:]
            run_id = name.removesuffix(".json")
            if (fips, run_id) not in out:
                d = DraftPack.model_validate_json(blob.download_as_bytes())
                out[(fips, run_id)] = _summary(d, "gcs")
    except Exception as e:
        log.error("draft listing from GCS failed: %s", e)
    return sorted(out.values(), key=lambda s: s["run_id"], reverse=True)


def get_draft(hazard: str, fips: str, run_id: str) -> DraftPack:
    # Path parts come from the URL: validate before they touch the filesystem or the bucket.
    if hazard not in ("hurricane", "winter") or not re.fullmatch(r"\d{5}", fips) or not RUN_ID_RE.match(run_id):
        raise KeyError(f"{hazard}/{fips}/{run_id}")
    local = LOCAL / hazard / fips / f"{run_id}.json"
    if local.exists():
        return DraftPack.model_validate_json(local.read_text())
    blob = _bucket().blob(f"{PREFIX}{hazard}/{fips}/{run_id}.json")
    if not blob.exists():
        raise KeyError(f"{hazard}/{fips}/{run_id}")
    return DraftPack.model_validate_json(blob.download_as_bytes())


def save_local(d: DraftPack) -> Path:
    p = LOCAL / d.target.hazard / d.target.fips / f"{d.run_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d.model_dump_json(indent=1))
    return p


def push(d: DraftPack) -> str:
    blob = _bucket().blob(f"{PREFIX}{d.target.hazard}/{d.target.fips}/{d.run_id}.json")
    blob.upload_from_string(d.model_dump_json(indent=1), content_type="application/json")
    return f"gs://{blob.bucket.name}/{blob.name}"


def dumps(d: DraftPack) -> dict:
    return json.loads(d.model_dump_json())
