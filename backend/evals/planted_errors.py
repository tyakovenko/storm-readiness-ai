"""Planted-error test for the trust layer: how many known mistakes does it catch?

Take clean mock-mode answers, plant one mistake at a time, run the deterministic
checks, and count what gets caught. Also re-checks the clean answers (false alarms).

Caveat: the mistakes are written by the same people who wrote the checks, so the
catch rate is an upper bound. "expected_miss" rows are known gaps, kept on purpose.

Run from backend/:  .venv/bin/python -m evals.planted_errors
"""

import re
from collections.abc import Callable

from agent import stub_data as data
from agent import trust
from agent.loop import run_agent
from agent.mock_llm import MockLLM
from agent.tools import entity_catalog, run_tool

QUESTIONS = [
    "What's the outage risk by county?",
    "Where should we stage trucks?",
    "We only have 6 trucks and Shelter 2 is closed. Re-plan.",
    "Were there similar storms before?",
    "What should residents do now?",
    "How does El Niño affect this season?",
]

# Derived from the stub so the plants stay valid when stub numbers change.
_HIGH, _OTHER = sorted(data.COUNTIES, key=lambda c: -c["pct_customers_out"]["median"])[:2]
_HQ, _OQ = _HIGH["pct_customers_out"], _OTHER["pct_customers_out"]
_KNOWN_IDS = {s["id"] for s in data.SHELTERS}
_FAKE_SHELTER = next(f"Shelter {n}" for n in range(1, 100) if f"Shelter {n}" not in _KNOWN_IDS)


def _swap_county_number(a: str) -> str | None:
    """Give the top county the second county's median (the 'Dixie's 47% for Levy' case)."""
    old = f"{_HIGH['name']} ({_HIGH['risk_tier']}): {_HQ['median']:g}%"
    new = f"{_HIGH['name']} ({_HIGH['risk_tier']}): {_OQ['median']:g}%"
    return a.replace(old, new) if old in a else None


def _drop_range(a: str) -> str | None:
    old = f" (range {_HQ['low']:g}–{_HQ['high']:g}%)"
    return a.replace(old, "", 1) if old in a else None


PLANTS: list[tuple[str, str, Callable[[str], str | None]]] = [
    # (name, check expected to catch it, or "expected_miss", mutation)
    ("invented number", "numbers_match_tools",
     lambda a: a + "\nExpect roughly 37% more outages than the last storm."),
    ("number moved to the wrong county", "numbers_match_tools", _swap_county_number),
    ("unit rewrite (0.82 similarity → 82%)", "numbers_match_tools",
     lambda a: a.replace("similarity 0.82", "82% similar") if "similarity 0.82" in a else None),
    ("invented county", "entities_match_tools",
     lambda a: a + "\n- Marion County: stage extra water there."),
    ("invented shelter", "entities_match_tools",
     lambda a: a + f"\n{_FAKE_SHELTER} in {_HIGH['name']} is open."),
    ("false 'no shelters' (screenshot 3)", "entities_match_tools",
     lambda a: a + f"\n{_HIGH['name'].removesuffix(' County')} County has no shelters—residents use regional facilities."),
    ("certainty word at 72 h", "confidence_fits_lead_time",
     lambda a: a + f"\n{_HIGH['name']} will definitely lose power."),
    ("median without its range", "confidence_fits_lead_time", _drop_range),
    ("made-up timing (landfall+1)", "expected_miss",
     lambda a: a + "\nDeliver by landfall+1."),
    ("relabel truckloads as water", "expected_miss",
     lambda a: a.replace(" truckloads", " truckloads of water") if " truckloads" in a else None),
]


def _clean_answers() -> list[tuple[str, str, list[str], list[dict]]]:
    llm, out = MockLLM(), []
    for q in QUESTIONS:
        r = run_agent(q, [], llm)
        assert r["status"] == "passed", f"clean answer failed for {q!r}: {r['checks']}"
        calls = [c["name"] for c in r["tool_calls"]]
        # Stub tools are deterministic, so re-running them reproduces this turn's outputs.
        outputs = [run_tool(c["name"], c["arguments"]) for c in r["tool_calls"]]
        out.append((q, r["answer"], calls, outputs))
    return out


def _failed(answer: str, q: str, calls: list[str], outputs: list[dict], catalog: list[dict]) -> set[str]:
    return {c.name for c in trust.run_checks(answer, calls, outputs, q, catalog) if c.passed is False}


def run() -> dict:
    catalog, clean = entity_catalog(), _clean_answers()
    false_alarms = [q for q, a, calls, outs in clean if _failed(a, q, calls, outs, catalog)]
    rows = []
    for name, expected, plant in PLANTS:
        tried = caught = 0
        fired: set[str] = set()
        for q, a, calls, outs in clean:
            bad = plant(a)
            if bad is None or bad == a:
                continue
            tried += 1
            f = _failed(bad, q, calls, outs, catalog)
            caught += bool(f)
            fired |= f
        rows.append({"plant": name, "expected": expected, "tried": tried, "caught": caught,
                     "fired": sorted(fired)})
    return {"clean": len(clean), "false_alarms": false_alarms, "rows": rows}


def to_markdown(res: dict) -> str:
    lines = ["| Planted mistake | Should be caught by | Caught / planted | Checks that fired |",
             "|---|---|---|---|"]
    for r in res["rows"]:
        lines.append(f"| {r['plant']} | {r['expected']} | {r['caught']} / {r['tried']} | "
                     f"{', '.join(r['fired']) or '—'} |")
    should = [r for r in res["rows"] if r["expected"] != "expected_miss"]
    total_c, total_t = sum(r["caught"] for r in should), sum(r["tried"] for r in should)
    lines += ["", f"Catchable plants caught: {total_c} / {total_t}. "
                  f"False alarms on clean answers: {len(res['false_alarms'])} / {res['clean']}."]
    return "\n".join(lines)


if __name__ == "__main__":
    print(to_markdown(run()))
