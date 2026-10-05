"""Research one county, then judge the draft.

    python -m research.run --fips 48201                  # research + judge -> data/processed/packs_draft/hurricane/48201/<run_id>.json
    python -m research.run --fips 48201 --no-judge       # research only
    python -m research.run --fips 48201 --review <run_id> # judge an existing draft again (e.g. new judge model)
    ... --push                                           # also gs://<bucket>/processed/packs_draft/...
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from research import config, policy


def _report(draft) -> str:
    log = draft.run_log
    counts: dict[str, int] = {}
    for r in draft.reviews:
        counts[r.verdict.value] = counts.get(r.verdict.value, 0) + 1
    caps = [c for c, hit in (("MODEL-CALL CAP", log.get("cap_hit") and not log.get("time_cap_hit")),
                             ("TIME CAP", log.get("time_cap_hit"))) if hit]
    return (f"{len(draft.facts)} facts, {len(draft.gaps)} gaps, {len(log.get('rejected_submissions', []))} rejected "
            f"submissions, {log.get('model_calls')} researcher calls, {log.get('fetches')} fetches "
            f"({len(log.get('fetch_errors', {}))} errors), {log.get('seconds')} s"
            + (f" | PARTIAL: {', '.join(caps)}" if caps else "")
            + (f"\nverdicts: {counts} (judge {draft.judge_model}, {log.get('judge_model_calls')} calls)" if draft.reviews else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fips", required=True)
    ap.add_argument("--model", default=config.RESEARCH_MODEL)
    ap.add_argument("--judge-model", default=config.JUDGE_MODEL)
    ap.add_argument("--max-calls", type=int, default=policy.MAX_GEMINI_CALLS)
    ap.add_argument("--max-seconds", type=int, default=policy.MAX_RUN_SECONDS)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--review", metavar="RUN_ID", help="judge an existing draft instead of researching")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config.vertex_env()

    from agent.adk_runner import check_model
    from research import store
    from research.judge import Judge

    # Validate every model this run will use now, not after minutes of research.
    if not a.review:
        check_model(a.model)
    if not a.no_judge:
        check_model(a.judge_model)

    if a.review:
        draft = store.get_draft("hurricane", a.fips, a.review)
    else:
        from research.researcher import run_research
        from research.targets import target_from_pack
        target, gaps, portals = target_from_pack(a.fips)
        draft = asyncio.run(run_research(target, gaps, portals, a.model, a.max_calls, max_seconds=a.max_seconds))
        print(f"draft: {store.save_local(draft)}")  # saved before judging: a judge failure keeps the research
    if not a.no_judge:
        draft = Judge(a.judge_model).review(draft)
    print(f"{store.save_local(draft)}\n{_report(draft)}")
    if a.push:
        print(store.push(draft))


if __name__ == "__main__":
    main()
