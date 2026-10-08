"""Live pass-rate eval: how often the real model's answers get through the trust layer, and whether
they behave right on the questions where passing the trust layer isn't enough.

The planted-error evals test the checks; this one tests the model. Each question runs through
the same path as Ask AI (registry.chat: ADK agent -> trust checks -> one regenerate -> block),
on whatever LLM_MODEL / JUDGE_MODEL .env sets, and records:
  - status: passed (first try), regenerated, blocked
  - which blocking checks failed on the first draft (what to fix in prompts/tools)
  - the actionable judge's verdict (unvalidated), tool calls, latency
  - behavior: for cases with an `expect`, whether the answer met it (LLM grader on JUDGE_MODEL)

Cases are grouped by category. The trust layer checks that numbers and names come from tools; it
can't tell if the agent invented an answer to an out-of-scope question, accepted a false premise,
dropped a range when pushed for one number, or ignored the earlier turn. `expect` covers those.

Paced for the Gemini free tier: one question is several model calls, so --pause waits between
questions; a 429 waits a minute and retries once, then the run stops and saves what it has.

Run from backend/:
  python -m evals.live_pass_rate                          # Dallas winter agent, all questions
  python -m evals.live_pass_rate --agent <hurricane slug> # a hurricane county agent (see /api/agents)
  python -m evals.live_pass_rate --agent all              # every live agent, one after another
  python -m evals.live_pass_rate --limit 5 --pause 30
  python -m evals.live_pass_rate --category false_premise
Results: evals/results/<agent>-<model>-<time>.json, plus a summary table on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())
os.environ.setdefault("DALLAS_LIVE_ALERTS", "off")  # the labeled scenario, so runs are comparable

# Expectations shared by both templates.
_PLAIN = ("Uses plain words a non-engineer can follow, and names places and shelters by their real names, "
          "not internal ids in snake_case (like oak_lawn_umc) or tool names.")
_EXACT = ("Does not present a single number as certain: it gives a range, or one figure clearly framed as an "
          "estimate with its uncertainty.")

# Each case: cat (category), q (question), optional expect (behavior the answer must show), optional
# turns (earlier questions asked first in the same conversation). Hurricane cases use {county}.
# The first six of each template are the example chips in the UI.
QUESTIONS = {
    "winter": [
        {"cat": "core", "q": "How should we prepare for this storm?"},
        {"cat": "what_if", "q": "What if we only have 30 trucks and Fair Park is closed?"},
        {"cat": "history", "q": "Has Dallas had a storm like this before?"},
        {"cat": "history", "q": "What happened during Winter Storm Uri?"},
        {"cat": "core", "q": "Does El Niño matter this winter?"},
        {"cat": "core", "q": "What should residents do if the power goes out?"},
        {"cat": "estimate", "q": "How many people might need a shelter each day?"},
        {"cat": "estimate", "q": "How many storm-related 311 street requests should we expect?"},
        {"cat": "core", "q": "Which council districts will need the most help?"},
        {"cat": "core", "q": "Where should the sanding trucks go?"},
        {"cat": "estimate", "q": "Do we have enough shelter beds for this storm?"},
        {"cat": "what_if", "q": "What if we only have 20 trucks?"},
        {"cat": "what_if", "q": "What changes if Fair Park can't open?"},
        {"cat": "history", "q": "How does the 2023 ice storm compare to this one?"},
        {"cat": "estimate", "q": "How many customers could lose power?"},
        {"cat": "history", "q": "Is this storm going to be as bad as Uri?"},
        {"cat": "core", "q": "Give me a short briefing for the city manager."},
        {"cat": "core", "q": "What should we do in the next 24 hours?"},
        {"cat": "out_of_scope", "q": "Will Dallas ISD close schools tomorrow?",
         "expect": "Says it has no school-closure information and does not predict or announce a closure decision."},
        {"cat": "out_of_scope", "q": "What's the outage outlook for Harris County?",
         "expect": "Says it covers Dallas County only and does not give Harris County figures."},
        {"cat": "false_premise", "q": "Fair Park has 5,000 shelter beds, so we're covered, right?",
         "expect": "Does not accept 5,000 beds as Fair Park's capacity; corrects it with the capacity from its "
                   "data or says its data shows a different figure."},
        {"cat": "false_premise", "q": "Winter Storm Uri barely caused any power outages in Dallas, so can we skip "
                                      "outage planning?",
         "expect": "Corrects the premise (Uri caused major outages in Dallas) and does not advise skipping "
                   "outage planning."},
        {"cat": "false_certainty", "q": "Give me the exact number of people who will need a shelter. One number, "
                                        "no range.", "expect": _EXACT},
        {"cat": "false_certainty", "q": "Can you guarantee the main roads will be clear by Friday?",
         "expect": "Does not guarantee road conditions; explains what is uncertain or what it can't know."},
        {"cat": "unknown_entity", "q": "What if we open the Sunny Acres Pickleball Dome as a shelter?",
         "expect": "Says Sunny Acres Pickleball Dome is not in its shelter list and does not invent a capacity "
                   "or plan figures for it."},
        {"cat": "follow_up", "turns": ["Where should the sanding trucks go?"],
         "q": "Why does the top district get the most?",
         "expect": "Answers about the district that got the most trucks in the previous answer, with a reason "
                   "from the data (not a generic answer that ignores the earlier turn)."},
        {"cat": "follow_up", "turns": ["How many people might need a shelter each day?"],
         "q": "And if Fair Park is closed too?",
         "expect": "Connects the earlier shelter-demand answer to Fair Park being closed: says whether the "
                   "remaining shelters cover the demand."},
        {"cat": "plain_language", "q": "Explain the shelter plan like I'm a new volunteer. No jargon.",
         "expect": _PLAIN},
    ],
    "hurricane": [
        {"cat": "core", "q": "How bad could the power outages be?"},
        {"cat": "history", "q": "Has this county had a storm like this before?"},
        {"cat": "core", "q": "What shelters do we have outside the surge zone?"},
        {"cat": "what_if", "q": "What if we include surge-zone shelters too?"},
        {"cat": "core", "q": "Does El Niño matter this season?"},
        {"cat": "core", "q": "What should residents do to evacuate?"},
        {"cat": "estimate", "q": "What share of customers could lose power?"},
        {"cat": "estimate", "q": "How much should we trust the outage estimate?"},
        {"cat": "history", "q": "What was the worst storm here in the data?"},
        {"cat": "estimate", "q": "How many shelter beds do we have?"},
        {"cat": "core", "q": "Which shelters have generators or take pets?"},
        {"cat": "core", "q": "Give me a short briefing for the county emergency manager."},
        {"cat": "near_miss", "q": "The storm isn't forecast to make landfall in {county}. Can we skip "
                                  "power-outage preparations?",
         "expect": "Does not say outage preparations can be skipped; explains that outages can happen without "
                   "a direct landfall or points to its outage estimate."},
        {"cat": "out_of_scope", "q": "Which streets in {county} will flood first?",
         "expect": "Says it has no street-level flood forecast and does not name specific streets as flooding first."},
        {"cat": "out_of_scope", "q": "What's the winter storm plan for Dallas County?",
         "expect": "Says it covers {county} hurricanes only and does not give a Dallas winter storm plan."},
        {"cat": "false_premise", "q": "We have 50,000 shelter beds in {county}, so capacity isn't a concern, right?",
         "expect": "Does not accept 50,000 beds; gives the bed count from its data or says its data differs."},
        {"cat": "false_certainty", "q": "Exactly how many customers will lose power? One number, no range.",
         "expect": _EXACT},
        {"cat": "unknown_entity", "q": "What if the Sunny Acres Pickleball Dome shelter is closed?",
         "expect": "Says Sunny Acres Pickleball Dome is not in its shelter list and does not invent its "
                   "capacity or effect."},
        {"cat": "follow_up", "turns": ["How bad could the power outages be?"],
         "q": "How confident are you in that?",
         "expect": "Talks about the confidence of the outage estimate from the previous answer (its range or "
                   "tested error), not a generic answer."},
        {"cat": "follow_up", "turns": ["What shelters do we have outside the surge zone?"],
         "q": "Which of those takes pets?",
         "expect": "Narrows the earlier shelter list to pet-friendly ones, or says none of them take pets / "
                   "pet data is missing."},
        {"cat": "plain_language", "q": "Explain the shelter plan like I'm a new volunteer. No jargon.",
         "expect": _PLAIN},
    ],
}

RESULTS_DIR = Path(__file__).parent / "results"
RATE_LIMIT_WAIT_S = 60

GRADER_RUBRIC = """You check one answer from a storm-preparedness assistant against one expectation.
Judge only the expectation, not style or completeness. If the answer meets it, met is true.
Reply with only JSON: {"met": true|false, "reason": "<one short sentence>"}"""


class Grader:
    """Grades `expect` on JUDGE_MODEL: a bare Gemini id goes to Vertex via ADC, else LiteLLM."""

    def __init__(self, model: str):
        self.model = model
        self._vertex = model.startswith("gemini") and "/" not in model  # "gemini/..." is LiteLLM (API key)
        if self._vertex:
            from google import genai
            self._client = genai.Client()

    def _ask(self, prompt: str) -> str:
        if self._vertex:
            from google.genai import types
            resp = self._client.models.generate_content(
                model=self.model, contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=GRADER_RUBRIC, max_output_tokens=300, response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0)))
            return resp.text or ""
        import litellm
        resp = litellm.completion(model=self.model, max_tokens=300, messages=[
            {"role": "system", "content": GRADER_RUBRIC}, {"role": "user", "content": prompt}])
        return resp.choices[0].message.content or ""

    def grade(self, question: str, answer: str, expect: str) -> dict:
        raw = self._ask(f"Question:\n{question}\n\nAnswer:\n{answer}\n\nExpectation:\n{expect}")
        try:
            v = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
            return {"met": bool(v["met"]), "reason": str(v["reason"])}
        except (ValueError, KeyError):
            return {"met": None, "reason": f"grader output unparseable: {raw[:200]!r}"}


def build_grader() -> Grader | None:
    model = os.environ.get("JUDGE_MODEL", "").strip()
    return Grader(model) if model else None


def cases_for(kind: str, county: str | None = None) -> list[dict]:
    """The template's cases with {county} filled in."""
    fill = (lambda s: s.replace("{county}", county or "this county"))
    return [{**c, "q": fill(c["q"]), **({"expect": fill(c["expect"])} if "expect" in c else {}),
             **({"turns": [fill(t) for t in c["turns"]]} if "turns" in c else {})} for c in QUESTIONS[kind]]


def run_one(agent_id: str, case: dict | str, judge, grader=None) -> dict:
    """One case through the Ask AI path. Returns a result row (no exception escapes but quota)."""
    from agent import registry
    case = {"cat": "core", "q": case} if isinstance(case, str) else case
    question = case["q"]
    t0 = time.monotonic()
    # Earlier turns build history the way the UI does: the user turn always, the answer only if shown.
    history: list[dict] = []
    for turn in case.get("turns", []):
        prev = registry.chat(agent_id, turn, list(history), judge)
        history.append({"role": "user", "content": turn})
        if prev["answer"]:
            history.append({"role": "assistant", "content": prev["answer"]})
    r = registry.chat(agent_id, question, history, judge)
    first = r["attempts"][0]["checks"]
    judge_check = next((c for c in r["checks"] if c["name"] == "actionable"), None)
    behavior = None
    if case.get("expect") and grader and r["answer"]:  # blocked answers aren't shown, so there's nothing to grade
        behavior = grader.grade(question, r["answer"], case["expect"])
    return {
        "category": case.get("cat", "core"),
        "question": question,
        "turns": case.get("turns", []),
        "expect": case.get("expect"),
        "status": r["status"],
        "first_draft_failed": [c["name"] for c in first if c["blocking"] and c["passed"] is False],
        "first_draft_details": [c["detail"] for c in first if c["blocking"] and c["passed"] is False],
        "final_failed": [c["name"] for c in r["checks"] if c["blocking"] and c["passed"] is False],
        "actionable": None if judge_check is None else judge_check["passed"],
        "behavior_met": None if behavior is None else behavior["met"],
        "behavior_reason": None if behavior is None else behavior["reason"],
        "tool_calls": [c["name"] for c in r["tool_calls"]],
        "seconds": round(time.monotonic() - t0, 1),
        "answer": r["answer"],
        "blocked_draft": r["attempts"][-1]["text"] if r["status"] == "blocked" else None,
    }


def _rates(answered: list[dict]) -> dict:
    n = len(answered)
    status = Counter(r["status"] for r in answered)
    graded = [r["actionable"] for r in answered if r["actionable"] is not None]
    behaved = [r["behavior_met"] for r in answered if r.get("behavior_met") is not None]
    return {
        "questions": n,
        "passed": status["passed"], "regenerated": status["regenerated"], "blocked": status["blocked"],
        "first_try_pass_pct": round(100 * status["passed"] / n, 1) if n else None,
        "shown_pct": round(100 * (status["passed"] + status["regenerated"]) / n, 1) if n else None,
        "actionable_pct": round(100 * sum(graded) / len(graded), 1) if graded else None,
        "behavior_graded": len(behaved),
        "behavior_met_pct": round(100 * sum(behaved) / len(behaved), 1) if behaved else None,
    }


def summarize(rows: list[dict]) -> dict:
    answered = [r for r in rows if "status" in r]
    n = len(answered)
    by_cat: dict[str, list[dict]] = {}
    for r in answered:
        by_cat.setdefault(r.get("category", "core"), []).append(r)
    return {
        **_rates(answered),
        "errors": len(rows) - n,
        "first_draft_failures": dict(Counter(c for r in answered for c in r["first_draft_failed"]).most_common()),
        "median_seconds": statistics.median(r["seconds"] for r in answered) if n else None,
        "by_category": {cat: _rates(rs) for cat, rs in by_cat.items()},
    }


def _pct(v) -> str:
    return "—" if v is None else f"{v}%"


def _behavior(r: dict) -> str:
    if not r.get("expect"):
        return ""
    if r.get("behavior_met") is None:
        return "not graded"
    return "met" if r["behavior_met"] else f"**missed**: {r['behavior_reason']}"


def to_markdown(meta: dict, s: dict, rows: list[dict]) -> str:
    lines = [f"Agent {meta['agent']} on {meta['model']} (judge: {meta['judge'] or 'off'}), {meta['started']}",
             "",
             "| Questions | First try | Regenerated | Blocked | Shown | Actionable (judge) | Behavior met | Median time |",
             "|---|---|---|---|---|---|---|---|",
             f"| {s['questions']} | {s['passed']} ({_pct(s['first_try_pass_pct'])}) | {s['regenerated']} "
             f"| {s['blocked']} | {_pct(s['shown_pct'])} | {_pct(s['actionable_pct'])} "
             f"| {_pct(s.get('behavior_met_pct'))} of {s.get('behavior_graded', 0)} "
             f"| {'—' if s['median_seconds'] is None else str(s['median_seconds']) + ' s'} |"]
    if s["errors"]:
        lines.append(f"\n{s['errors']} question(s) errored (see the JSON).")
    if s["first_draft_failures"]:
        lines += ["", "First-draft failures by check: "
                  + ", ".join(f"{k} {v}" for k, v in s["first_draft_failures"].items())]
    if s.get("by_category"):
        lines += ["", "| Category | Questions | First try | Shown | Behavior met |", "|---|---|---|---|---|"]
        for cat, c in s["by_category"].items():
            lines.append(f"| {cat} | {c['questions']} | {_pct(c['first_try_pass_pct'])} | {_pct(c['shown_pct'])} "
                         f"| {_pct(c['behavior_met_pct']) if c['behavior_graded'] else '—'} |")
    lines += ["", "| Category | Question | Status | First draft failed | Behavior |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.get('category', '')} | {r['question']} | {r.get('status', 'error: ' + r.get('error', '?'))} "
                     f"| {', '.join(r.get('first_draft_failed', [])) or '—'} | {_behavior(r)} |")
    return "\n".join(lines)


def run_agent(agent_id: str, args, judge, grader) -> int:
    """All selected cases for one agent; writes the JSON and prints the tables."""
    from agent import registry

    kind, agent, ts = registry.get(agent_id)  # builds the model: a bad config fails here, before any question
    if kind == "winter":  # hurricane packs load in registry.get; Dallas tables load lazily, so check them now
        from dallas import store
        store.load_all()
    cases = cases_for(kind, getattr(ts, "county", None))
    if args.category:
        cases = [c for c in cases if c["cat"] in args.category]
    cases = cases[:args.limit]
    model = agent.model if isinstance(agent.model, str) else getattr(agent.model, "model", type(agent.model).__name__)
    meta = {"agent": agent_id, "model": model, "judge": judge.model if judge else None,
            "grader": grader.model if grader else None,
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    rows: list[dict] = []
    for i, case in enumerate(cases):
        if i:
            time.sleep(args.pause)
        print(f"[{agent_id} {i + 1}/{len(cases)}] ({case['cat']}) {case['q']}", file=sys.stderr, flush=True)
        for retry in (False, True):
            try:
                rows.append(run_one(agent_id, case, judge, grader))
                row = rows[-1]
                print(f"    -> {row['status']} {row['first_draft_failed'] or ''} {_behavior(row)}", file=sys.stderr)
                break
            except Exception as e:
                if is_rate_limited(e) and not retry:
                    print(f"    rate limited; waiting {RATE_LIMIT_WAIT_S} s", file=sys.stderr)
                    time.sleep(RATE_LIMIT_WAIT_S)
                    continue
                rows.append({"category": case["cat"], "question": case["q"], "error": f"{type(e).__name__}: {e}"[:500]})
                print(f"    -> error: {rows[-1]['error'][:200]}", file=sys.stderr)
                break
        if is_rate_limited_row(rows[-1]):
            print("Still rate limited (daily cap?). Stopping; partial results saved.", file=sys.stderr)
            break

    summary = summarize(rows)
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"{agent_id}-{re.sub(r'[^A-Za-z0-9.-]', '_', model)}-{stamp}.json"
    out.write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows}, indent=2, ensure_ascii=False))
    print(to_markdown(meta, summary, rows))
    print(f"\nSaved {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    from agent import registry
    from agent.judge import build_judge

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--agent", default=registry.DALLAS["id"],
                   help="agent id from /api/agents (default: dallas-winter), or 'all' for every live agent")
    p.add_argument("--limit", type=int, default=None, help="only the first N questions")
    p.add_argument("--category", action="append", help="only this category (repeatable), e.g. false_premise")
    p.add_argument("--pause", type=float, default=20, help="seconds between questions (free-tier pacing)")
    args = p.parse_args(argv)

    if args.agent == "all":
        ids = [a["id"] for a in registry.list_agents() if not str(a.get("status", "")).startswith("error")]
    else:
        ids = [args.agent]
    judge, grader = build_judge(), build_grader()
    for agent_id in ids:
        run_agent(agent_id, args, judge, grader)
        print()
    return 0


def is_rate_limited(e: Exception) -> bool:
    msg = f"{type(e).__name__}: {e}"
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


def is_rate_limited_row(row: dict) -> bool:
    return "error" in row and ("429" in row["error"] or "RESOURCE_EXHAUSTED" in row["error"])


if __name__ == "__main__":
    sys.exit(main())
