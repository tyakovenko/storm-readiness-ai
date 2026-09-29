"""The agent loop: plain tool calling, then the trust layer, then one regenerate.

    question -> LLM picks tools -> tools run -> LLM writes answer
             -> trust checks -> pass: show | fail: feed back and regenerate once | fail again: block
"""

import json
import logging

from . import judge as judge_mod
from . import trust
from .tools import TOOL_SCHEMAS, entity_catalog, run_tool

MAX_TOOL_ROUNDS = 8
TRUST_FEEDBACK_PREFIX = "[trust-layer]"

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Storm Readiness assistant. You help emergency managers \
understand a hurricane forecast's impact and the resource staging plan.

Rules:
- Never calculate, estimate or invent numbers. Every number, place and facility you \
mention must come from a tool result in this conversation. If no tool gives it, say you don't have it.
- In every turn, call get_advisory before any other tool so you use the current advisory.
- For any question about resources, trucks, shelters or staging, call solve_staging. Turn \
what-if statements into its arguments (e.g. "only 6 trucks" -> max_trucks=6; \
"Shelter 4 is closed" -> unavailable_sites=["Shelter 4"]). For a what-if, also call \
diff_plans with the same arguments and say what changed versus the full plan.
- The forecast is uncertain far from landfall. When you give a county's outage percentage, \
give its low-high range too, and never use certainty words (definitely, certainly, will lose power).
- For El Niño or seasonal questions, call get_enso_context; El Niño changes seasonal odds, \
never the forecast for this storm.
- When you give the shelter demand estimate, say it is an assumption.
- The data is demo stub data; say so briefly.
- Be brief: a few sentences or a short list. Plain language."""


def _run_tools(messages: list[dict], llm, calls: list[dict], outputs: list[dict]) -> str:
    for _ in range(MAX_TOOL_ROUNDS):
        turn = llm.complete(messages, TOOL_SCHEMAS)
        messages.append(turn.raw)
        if not turn.tool_calls:
            return turn.text
        for tc in turn.tool_calls:
            result = run_tool(tc.name, tc.arguments)
            calls.append({"name": tc.name, "arguments": tc.arguments})
            outputs.append(result)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
    raise RuntimeError(f"Agent did not finish within {MAX_TOOL_ROUNDS} tool rounds")


def _judge_check(judge, question: str, answer: str) -> trust.Check:
    if judge is None:
        return judge_mod.not_configured()
    try:
        return judge.grade(question, answer)
    except Exception as e:  # judge is advisory: surface the failure, don't drop the answer
        log.error("Actionable judge failed: %s", e)
        return trust.Check(judge_mod.NAME, None, False, f"Judge call failed: {e}")


def run_agent(question: str, history: list[dict], llm, judge=None) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                {"role": "user", "content": question}]
    all_calls, outputs, attempts = [], [], []
    catalog = entity_catalog()
    status = "blocked"

    for attempt in range(2):
        attempt_calls = []
        text = _run_tools(messages, llm, attempt_calls, outputs)
        all_calls += attempt_calls
        # Order is checked on this attempt's calls if it made any, so a retry that re-runs
        # the tools in order can pass; "was solve_staging called" looks at the whole turn.
        names_all = [c["name"] for c in all_calls]
        names_now = [c["name"] for c in attempt_calls] or names_all
        checks = trust.run_checks(text, names_all, outputs, question, catalog, order_calls=names_now)
        attempts.append({"text": text, "checks": trust.to_dicts(checks)})
        failed = [c for c in checks if c.blocking and c.passed is False]
        if not failed:
            status = "passed" if attempt == 0 else "regenerated"
            break
        messages.append({"role": "user", "content": (
            f"{TRUST_FEEDBACK_PREFIX} Your answer was blocked: "
            + "; ".join(c.detail for c in failed)
            + ". Rewrite it to fix these. Use only numbers from tool results; call tools again if you need to "
            "(if the tool order was wrong, call get_advisory first, then re-run the other tools). "
            "Reply with the corrected answer only: users never see this feedback, so don't apologize or mention it.")})

    # Judge runs once, on the answer users will see; a blocked answer is never graded.
    final = (_judge_check(judge, question, attempts[-1]["text"]) if status != "blocked"
             else trust.Check(judge_mod.NAME, None, False, "Not graded: answer was blocked"))
    attempts[-1]["checks"] += trust.to_dicts([final])

    impact = next((o for o in reversed(outputs) if "counties" in o), None)
    return {
        "status": status,
        "answer": attempts[-1]["text"] if status != "blocked" else None,
        "checks": attempts[-1]["checks"],
        "attempts": attempts,
        "tool_calls": all_calls,
        "sources": sorted({o["source"] for o in outputs if "source" in o}
                          | ({f"Impact model version: {impact['model_version']}"} if impact else set())),
        "why": [{"county": c["name"], "reasons": c["why"]} for c in impact["counties"]] if impact else [],
        "model": llm.model,
    }
