"""Trust layer: checks every agent answer before it is shown.

Built so far (deterministic):
  - numbers_match_tools: every number in the answer appears in a tool output
    (or in the user's own question, e.g. "we only have 6 trucks").
  - required_steps: get_advisory before any model tool, and no staging advice
    without solve_staging.
Still to design (Workstream C): confidence-fits-lead-time and actionable (LLM judge).
"""

import re
from dataclasses import asdict, dataclass

NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
LIST_MARKER_RE = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
STAGING_WORDS_RE = re.compile(r"\b(truck|truckload|pre-?position|staging|allocat)", re.IGNORECASE)
MODEL_TOOLS = {"generate_scenarios", "predict_impact", "solve_staging", "find_analogs"}


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
        return {float(value)}
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


def check_steps(answer: str, calls: list[str]) -> Check:
    problems = []
    for i, name in enumerate(calls):
        if name in MODEL_TOOLS and "get_advisory" not in calls[:i + 1]:
            problems.append(f"{name} ran without get_advisory first")
            break
    if STAGING_WORDS_RE.search(answer) and "solve_staging" not in calls:
        problems.append("staging advice given without calling solve_staging")
    if problems:
        return Check("required_steps", False, True, "; ".join(problems))
    return Check("required_steps", True, True, "Tool-call sequence OK")


def run_checks(answer: str, calls: list[str], tool_outputs: list[dict], question: str) -> list[Check]:
    return [
        check_numbers(answer, tool_outputs, question),
        check_steps(answer, calls),
        Check("confidence_fits_lead_time", None, False, "Not built yet (design TBD with Workstream C)"),
        Check("actionable", None, False, "Not built yet (LLM judge, needs human-labeled sample first)"),
    ]


def to_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]
