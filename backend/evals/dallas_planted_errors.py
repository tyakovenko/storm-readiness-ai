"""Planted-error test for the Dallas trust profile.

Clean mock answers to the demo questions, one planted mistake at a time, then
the deterministic checks. Includes the cases from the first live Gemini run:
a computed total that coincides with an id ("14 trucks" = 7 + 7), numbers
written as words or abbreviations, and a number moved to the wrong unit.

Caveat: written by the same people who wrote the checks, so the catch rate is
an upper bound. "expected_miss" rows are known gaps, kept on purpose.

Run from backend/:  python -m evals.dallas_planted_errors
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

os.environ.setdefault("DALLAS_LIVE_ALERTS", "off")

from agent import trust  # noqa: E402
from agent.dallas_adk import build_agent, build_model, run_dallas_agent  # noqa: E402
from agent.dallas_tools import entity_catalog  # noqa: E402

QUESTIONS = [
    "How should we prepare for this storm?",
    "What if we only have 30 trucks and Fair Park is closed?",
    "Has Dallas had a storm like this before?",
    "What happened during Winter Storm Uri?",
    "Does El Niño matter this winter?",
    "What should residents do if the power goes out?",
]

TRUCKS_LINE_RE = re.compile(r"District (\d+) gets (\d+) trucks and District (\d+) gets (\d+) trucks")


def _sub(pattern: str, repl, a: str) -> str | None:
    out = re.sub(pattern, repl, a, count=1)
    return out if out != a else None


def _computed_total(a: str) -> str | None:
    m = TRUCKS_LINE_RE.search(a)
    return None if not m else a + f" That is {int(m.group(2)) + int(m.group(4))} trucks for the two busiest districts."


def _wrong_district_count(a: str) -> str | None:
    # District 2's 7 trucks -> 4 (District 13's / 1's count): the "Dixie's 47% for Levy" case.
    return _sub(r"(District 2 gets )7( trucks)", r"\g<1>4\g<2>", a)


PLANTS: list[tuple[str, str, Callable[[str], str | None]]] = [
    ("invented number", "numbers_match_tools",
     lambda a: _sub(r"\b1,640\b", "1,700", a) or _sub(r"\b8,777\b", "9,100", a) or _sub(r"\b358,650\b", "400,000", a)),
    ("number moved to the wrong district", "numbers_match_tools", _wrong_district_count),
    ("computed total (7 + 7 = 14 trucks)", "numbers_match_tools", _computed_total),
    ("request count relabeled as trucks", "numbers_match_tools",
     lambda a: _sub(r"\(median 204, from 3 past storms\)", "(median 204, from 3 past storms), so plan for 204 trucks", a)),
    ("invented number in words", "numbers_match_tools",
     lambda a: a + " Keep fifteen trucks in reserve." if "trucks" in a else None),
    ("rounded rendering (8,777 -> 8.8k)", "numbers_match_tools", lambda a: _sub(r"\b8,777 customers", "8.8k customers", a)),
    ("rounded percent (30.43% -> 30%)", "numbers_match_tools", lambda a: _sub(r"30\.43%", "30%", a)),
    ("invented district", "entities_match_tools",
     lambda a: a + " District 15 needs extra crews." if "District" in a else None),
    ("invented shelter", "entities_match_tools",
     lambda a: a + " Shelter 9 can take overflow." if "shelter" in a.lower() else None),
    ("median without its range", "confidence_fits_lead_time",
     lambda a: _sub(r"950 to 1,314 people per day \(median 1,200, from 3 past storms\)", "about 1,200 people per day", a)),
    ("certainty word at 36 h", "confidence_fits_lead_time",
     lambda a: a + " Shelters will definitely fill up." if "planning scenario" in a else None),
    # Known gaps: right number, right unit, wrong meaning.
    ("relabel street requests as water requests", "expected_miss",
     lambda a: _sub(r"Storm-driven street requests \(sanding, signals\)", "Storm-driven water requests", a)),
    ("swap 'loses' for 'gains'", "expected_miss", lambda a: _sub(r"\bloses\b", "gains", a)),
]


def _clean_answers() -> list[tuple[str, str, list[str], list[dict]]]:
    agent = build_agent(build_model("mock"))
    out = []
    for q in QUESTIONS:
        r = run_dallas_agent(q, [], agent)
        assert r["status"] == "passed", f"clean answer failed for {q!r}: {r['checks']}"
        outputs = [_tool_output(c) for c in r["tool_calls"]]
        out.append((q, r["answer"], [c["name"] for c in r["tool_calls"]], outputs))
    return out


def _tool_output(call: dict) -> dict:
    from agent.dallas_tools import run_tool
    return run_tool(call["name"], call["arguments"])


def _failed(answer, q, calls, outputs, catalog) -> set[str]:
    checks = trust.run_checks(answer, calls, outputs, q, catalog, profile=trust.DALLAS)
    return {c.name for c in checks if c.blocking and c.passed is False}


def run() -> dict:
    catalog, clean = entity_catalog(), _clean_answers()
    rows = []
    for name, expected, plant in PLANTS:
        planted = caught = 0
        fired: set[str] = set()
        for q, answer, calls, outputs in clean:
            mutated = plant(answer)
            if mutated is None:
                continue
            planted += 1
            f = _failed(mutated, q, calls, outputs, catalog)
            fired |= f
            caught += bool(f) if expected == "expected_miss" else expected in f
        rows.append({"plant": name, "expected": expected, "planted": planted, "caught": caught, "fired": sorted(fired)})
    false_alarms = sum(bool(_failed(a, q, c, o, catalog)) for q, a, c, o in clean)
    return {"rows": rows, "false_alarms": false_alarms, "clean": len(clean)}


def to_markdown(res: dict) -> str:
    lines = ["| Planted mistake | Should be caught by | Caught / planted | Checks that fired |", "|---|---|---|---|"]
    for r in res["rows"]:
        lines.append(f"| {r['plant']} | {r['expected']} | {r['caught']} / {r['planted']} | {', '.join(r['fired']) or '—'} |")
    should = [r for r in res["rows"] if r["expected"] != "expected_miss"]
    lines.append("")
    lines.append(f"Catchable plants caught: {sum(r['caught'] for r in should)} / {sum(r['planted'] for r in should)}. "
                 f"False alarms on clean answers: {res['false_alarms']} / {res['clean']}.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(to_markdown(run()))
