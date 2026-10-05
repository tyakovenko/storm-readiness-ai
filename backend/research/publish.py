"""Publish reviewed facts from a draft into the county's live pack. The human step (ADR research-offline-human-gate).

    python -m research.publish --fips 48201 --run <run_id> --reviewer "Taya" --accept verified,single_source \
        [--reject f3,f7] [--also f9] [--push]

--accept takes verdicts; --reject drops facts by id even if their verdict is accepted; --also adds facts by id
whatever their verdict (after reading the source yourself). Conflicting/unsupported/unchecked facts are only
published through --also. Every published fact keeps its verdict, checks and the reviewer's name.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from research import store
from research.schema import DraftPack, Verdict

ACCEPTABLE = {Verdict.VERIFIED.value, Verdict.SINGLE_SOURCE.value}  # what --accept may name


def select(draft: DraftPack, accept: set[str], reject: set[str], also: set[str]) -> list[dict]:
    if not draft.reviews:
        raise ValueError("draft has no judge reviews: run `python -m research.run --review <run_id>` first")
    bad = accept - ACCEPTABLE
    if bad:
        raise ValueError(f"--accept may only name {sorted(ACCEPTABLE)}; use --also for single facts ({sorted(bad)})")
    ids = {f.id for f in draft.facts}
    unknown = (reject | also) - ids
    if unknown:
        raise ValueError(f"unknown fact ids: {sorted(unknown)}")
    reviews = {r.fact_id: r for r in draft.reviews}
    out = []
    for f in draft.facts:
        r = reviews.get(f.id)
        verdict = r.verdict.value if r else "unreviewed"
        if f.id in reject or not (verdict in accept or f.id in also):
            continue
        out.append({**json.loads(f.model_dump_json()), "verdict": verdict,
                    "corroborating_urls": r.corroborating_urls if r else [],
                    "checks": [c.model_dump() for c in r.checks] if r else [],
                    "reviewer_override": f.id in also and verdict not in accept})
    return out


def publish(fips: str, run_id: str, reviewer: str, accept: set[str], reject: set[str], also: set[str],
            push: bool = False) -> dict:
    from hurricane import store as packs
    draft = store.get_draft("hurricane", fips, run_id)
    facts = select(draft, accept, reject, also)
    pack = dict(packs.pack(fips))
    pack["facts"] = facts
    pack["research"] = {"run_id": run_id, "researcher_model": draft.researcher_model, "judge_model": draft.judge_model,
                        "reviewer": reviewer, "approved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "accepted_verdicts": sorted(accept), "rejected": sorted(reject), "overrides": sorted(also),
                        "gaps_reported": [g.model_dump() for g in draft.gaps]}
    local = packs.LOCAL / fips / "pack.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(pack, indent=1))
    packs.table.cache_clear()
    if push:
        packs._blob(f"processed/packs/hurricane/{fips}/pack.json").upload_from_filename(
            str(local), content_type="application/json")
    return {"pack": str(local), "facts": len(facts), "pushed": push}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fips", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--accept", default="", help="comma list of verdicts: verified,single_source")
    ap.add_argument("--reject", default="")
    ap.add_argument("--also", default="")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    split = lambda s: {x.strip() for x in s.split(",") if x.strip()}  # noqa: E731
    print(publish(a.fips, a.run, a.reviewer, split(a.accept), split(a.reject), split(a.also), a.push))


if __name__ == "__main__":
    main()
