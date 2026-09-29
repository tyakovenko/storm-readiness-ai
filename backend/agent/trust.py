"""Trust layer: checks every agent answer before it is shown.

Deterministic (blocking; a fail triggers one regenerate, then a block):
  - numbers_match_tools: every number in the answer appears in a tool output
    (or in the user's own question, e.g. "we only have 6 trucks").
  - required_steps: get_advisory before any model tool, no staging advice
    without solve_staging, no tool output from a different advisory.
  - confidence_fits_lead_time: when the forecast is uncertain (long lead time or
    wide scenario spread), no certainty words and outage numbers carry their range.
LLM judge (non-blocking, flags for the reviewer): actionable. See judge.py.
"""

import re
from dataclasses import asdict, dataclass

NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
LIST_MARKER_RE = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
STAGING_WORDS_RE = re.compile(r"\b(truck|truckload|pre-?position|staging|allocat)", re.IGNORECASE)
MODEL_TOOLS = {"generate_scenarios", "get_enso_context", "predict_impact", "solve_staging",
               "diff_plans", "find_analogs"}

# Proposal §4.5: allowed certainty depends on lead time and scenario disagreement.
# 48 h is the NHC hurricane-warning horizon; beyond it track error is large enough
# that point claims overstate what the forecast knows. Both are calibration
# targets for the approve/reject log, not settled values.
UNCERTAIN_LEAD_TIME_H = 48
UNCERTAIN_SPREAD_NM = 60
CERTAINTY_RE = re.compile(
    r"\b(definitely|certainly|guarantee[ds]?|for sure|without (?:a )?doubt|no doubt|"
    r"will (?:lose|be without) power|will be (?:hit|flooded|destroyed))\b", re.IGNORECASE)
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


@dataclass
class Check:
    name: str
    passed: bool | None  # None = not built yet
    blocking: bool
    detail: str


def _numbers_in_text(text: str) -> set[float]:
    text = LIST_MARKER_RE.sub("", text)
    return {float(m.replace(",", "")) for m in NUMBER_RE.findall(text) if m.replace(",", "")}


def _numbers_in_output(value) -> set[float]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        # abs: the number regex drops signs, so "-2" in a diff reads as "2" in the answer.
        return {float(value), abs(float(value))}
    if isinstance(value, str):
        return _numbers_in_text(value)
    if isinstance(value, dict):
        return set().union(*(_numbers_in_output(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_numbers_in_output(v) for v in value)) if value else set()
    return set()


def check_numbers(answer: str, tool_outputs: list[dict], question: str) -> Check:
    allowed = _numbers_in_output(tool_outputs) | _numbers_in_text(question)
    unmatched = sorted(n for n in _numbers_in_text(answer) if n not in allowed)
    if unmatched:
        shown = ", ".join(f"{n:g}" for n in unmatched)
        return Check("numbers_match_tools", False, True, f"Numbers not found in any tool output: {shown}")
    return Check("numbers_match_tools", True, True, "Every number traces back to a tool output")


def check_steps(answer: str, calls: list[str], tool_outputs: list[dict]) -> Check:
    problems = []
    for i, name in enumerate(calls):
        if name in MODEL_TOOLS and "get_advisory" not in calls[:i + 1]:
            problems.append(f"{name} ran without get_advisory first")
            break
    if STAGING_WORDS_RE.search(answer) and "solve_staging" not in calls:
        problems.append("staging advice given without calling solve_staging")
    current = next((o["advisory_number"] for o in reversed(tool_outputs) if "storm_name" in o), None)
    stale = sorted({o["advisory_number"] for o in tool_outputs
                    if "advisory_number" in o and o["advisory_number"] != current})
    if current is not None and stale:
        problems.append(f"tool output from advisory {stale} mixed with current advisory {current}")
    if problems:
        return Check("required_steps", False, True, "; ".join(problems))
    return Check("required_steps", True, True, "Tool-call sequence OK")


def check_confidence(answer: str, tool_outputs: list[dict]) -> Check:
    name = "confidence_fits_lead_time"
    advisory = next((o for o in reversed(tool_outputs) if "lead_time_to_landfall_h" in o), None)
    if advisory is None:
        return Check(name, None, False, "No advisory in tool outputs, so lead time is unknown")
    lead = advisory["lead_time_to_landfall_h"]
    spread = next((o["landfall_spread_nm"] for o in reversed(tool_outputs) if "landfall_spread_nm" in o), None)
    reasons = [f"lead time {lead:g} h > {UNCERTAIN_LEAD_TIME_H} h"] if lead > UNCERTAIN_LEAD_TIME_H else []
    if spread is not None and spread > UNCERTAIN_SPREAD_NM:
        reasons.append(f"scenario spread {spread:g} nm > {UNCERTAIN_SPREAD_NM} nm")
    if not reasons:
        return Check(name, True, True, f"Lead time {lead:g} h: forecast is firm enough for point estimates")

    problems = [f'certainty word "{m}"' for m in dict.fromkeys(CERTAINTY_RE.findall(answer))]
    # A county's median % without its low and high hides the uncertainty.
    impact = next((o for o in reversed(tool_outputs) if "counties" in o), None)
    stated_pcts = {float(p) for p in PCT_RE.findall(answer)}
    answer_nums = _numbers_in_text(answer)
    for c in impact["counties"] if impact else []:
        q = c["pct_customers_out"]
        if c["name"] in answer and float(q["median"]) in stated_pcts \
                and not {float(q["low"]), float(q["high"])} <= answer_nums:
            problems.append(f"{c['name']} outage given without its range ({q['low']:g}–{q['high']:g}%)")
    context = " and ".join(reasons)
    if problems:
        return Check(name, False, True, f"Forecast is uncertain ({context}) but the answer has: "
                     + "; ".join(problems) + ". State the range and drop certainty words")
    return Check(name, True, True, f"No certainty words; outage figures carry ranges ({context})")


def run_checks(answer: str, calls: list[str], tool_outputs: list[dict], question: str) -> list[Check]:
    """Deterministic checks. The actionable judge runs separately, on the final answer only."""
    return [
        check_numbers(answer, tool_outputs, question),
        check_steps(answer, calls, tool_outputs),
        check_confidence(answer, tool_outputs),
    ]


def to_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]
