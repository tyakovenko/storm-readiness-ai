"""Gold-set eval for the research layer (plan R5).

    python -m evals.research_gold --fips 48201 --validate        # every gold fact must pass the fixed checks live
    python -m evals.research_gold --fips 48201 --run <run_id>    # score a judged draft against the gold set

Gold facts are specs (evals/gold/<fips>.json): the number as written + URL; built by reference from the live
page, the same way the researcher's facts are. Scores:
  recall           gold facts (merging same_as duplicates) found by the draft: same metric, storm, place, value ±2 %
  verdicts         judge verdicts on the matched facts
  false_verified   VERIFIED draft facts that match a decoy, or contradict a gold fact (same metric/storm/place,
                   value outside tolerance, no gold match). The gating metric: must be 0.
  unscored         draft facts the gold set says nothing about (reviewer judgment, not counted either way)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from research import numbers, policy
from research.fetch import Fetcher
from research.schema import DraftPack, Fact, FactDraft, Target, Verdict
from research.verify import check_fact, fixed_verdict

GOLD = Path(__file__).parent / "gold"


def load(fips: str) -> dict:
    return json.loads((GOLD / f"{fips}.json").read_text())


def build(spec: dict, page, retrieved: str) -> Fact:
    spans = numbers.extract(page.text)
    span = next((s for s in spans if s.raw == spec["value_raw"] and s.usable), None)
    if span is None:
        raise ValueError(f"{spec['id']}: {spec['value_raw']!r} not found as a usable number on the page")
    d = FactDraft(id=spec["id"], metric=spec["metric"], unit=spec["unit"], value_ref=span.id,
                  storm_id=spec.get("storm_id"), place=spec.get("place"), subject=spec["subject"],
                  source="gold", source_url=page.final_url or spec["source_url"], retrieved=retrieved)
    return numbers.fact_from_ref(d, spans, page.text)


def validate(fips: str, target: Target, fetch=None) -> list[dict]:
    fetch = fetch or Fetcher()
    rows = []
    for spec in load(fips)["facts"]:
        page = fetch(spec["source_url"])
        if page.error:
            rows.append({"id": spec["id"], "ok": None, "detail": f"unchecked: {page.error}"})
            continue
        try:
            f = build(spec, page, page.retrieved or "2026-10-05")
        except ValueError as e:
            rows.append({"id": spec["id"], "ok": False, "detail": str(e).splitlines()[-1][:160]})
            continue
        checks = check_fact(f, page, target)
        bad = [f"{c.name}: {c.detail}" for c in checks if c.ok is False and c.severity == "block"]
        rows.append({"id": spec["id"], "ok": fixed_verdict(checks) is None, "value": f.value,
                     "detail": "; ".join(bad) or f.quote[:120]})
    return rows


def _key(x: dict) -> tuple:
    return x["metric"], x.get("storm_id"), (x.get("place") or None)


def _same_subject(f: dict, g: dict) -> bool:
    a, b = (f.get("subject") or "").lower(), (g.get("subject") or "").lower()
    return bool(a and b) and (a in b or b in a)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= policy.CORROBORATION_TOLERANCE * max(abs(a), abs(b), 1)


def _value(spec: dict) -> float:
    return numbers.extract(spec["value_raw"])[0].value


def score(draft: DraftPack, gold: dict) -> dict:
    verdicts = {r.fact_id: r.verdict for r in draft.reviews}
    facts = [json.loads(f.model_dump_json()) for f in draft.facts]
    gold_facts = [{**g, "value": _value(g)} for g in gold["facts"]]
    groups: dict[str, list[dict]] = {}
    for g in gold_facts:  # same_as merges two sources of one fact into one recall target
        groups.setdefault(g.get("same_as") or g["id"], []).append(g)
    found, matched_ids = {}, set()
    for gid, members in groups.items():
        for f in facts:
            if any(_key(f) == _key(g) and f["value"] is not None and _close(f["value"], g["value"]) for g in members):
                found.setdefault(gid, []).append(f["id"])
                matched_ids.add(f["id"])
    false_verified = []
    for f in facts:
        if verdicts.get(f["id"]) is not Verdict.VERIFIED or f["value"] is None:
            continue
        for d in gold.get("decoys", []):
            if (f["metric"], f.get("storm_id")) == (d["metric"], d.get("storm_id")) and _close(f["value"], d["value"]) \
                    and not (d.get("unless_subject") and d["unless_subject"].lower() in (f.get("subject") or "").lower()):
                false_verified.append({"fact": f["id"], "why": f"decoy: {d['why']}"})
        # Same metric/storm/place with another value is a contradiction only for the same subject: NRG's 3,365
        # and the Red Cross's 14,154 are both true Harvey evacuee counts.
        if f["id"] not in matched_ids and any(_key(f) == _key(g) and _same_subject(f, g) for g in gold_facts):
            false_verified.append({"fact": f["id"], "why": "contradicts a gold fact (same metric/storm/place/subject, other value)"})
    counts: dict[str, int] = {}
    for ids in found.values():
        for i in ids:
            v = verdicts.get(i)
            counts[v.value if v else "unreviewed"] = counts.get(v.value if v else "unreviewed", 0) + 1
    return {"recall": f"{len(found)}/{len(groups)}", "found": found, "missed": sorted(set(groups) - set(found)),
            "matched_verdicts": counts, "false_verified": false_verified,
            "unscored": len([f for f in facts if f["id"] not in matched_ids])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fips", required=True)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--run")
    a = ap.parse_args()
    from research import store
    from research.targets import target_from_pack
    target, _, _ = target_from_pack(a.fips)
    if a.validate:
        for r in validate(a.fips, target):
            print(f"{r['id']:4} {'PASS' if r['ok'] else 'UNCHECKED' if r['ok'] is None else 'FAIL'}  {r['detail']}")
    if a.run:
        print(json.dumps(score(store.get_draft(target.hazard, a.fips, a.run), load(a.fips)), indent=1))


if __name__ == "__main__":
    main()
