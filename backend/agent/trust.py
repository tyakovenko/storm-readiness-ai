"""Trust layer: checks every agent answer before it is shown.

Deterministic (blocking; a fail triggers one regenerate, then a block):
  - numbers_match_tools: every number in the answer appears in a tool output
    (or in the user's own question, e.g. "we only have 6 trucks"). In a sentence
    that names a county or shelter, the number must come from that entity's own
    records or from a non-entity field: Dixie's 47% can't be reused for Levy.
  - entities_match_tools: every county/shelter named came back from a tool this
    turn; "no shelters in X" needs a query_assets lookup for X that came back empty.
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

# Lines, then sentences/clauses: a number binds to the entities in its own clause.
CLAUSE_SPLIT_RE = re.compile(r"\n|(?<=[.!?;])\s+")
# Names that look like places/facilities but may not be in the catalog (invented ones).
COUNTY_MENTION_RE = re.compile(r"\b((?:[A-Z][a-z]+ )*[A-Z][a-z]+) County\b")
SHELTER_ID_RE = re.compile(r"\bShelter \d+\b")
SHELTER_ABSENCE_RE = re.compile(
    r"\b(?:no|zero|without any)\s+(?:open\s+|public\s+|available\s+)?shelters?\b", re.IGNORECASE)


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


def _mentions(text: str, catalog: list[dict]) -> list[dict]:
    return [e for e in catalog
            if any(re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", text) for n in e["names"])]


def _binds(d: dict, e: dict) -> bool:
    """A tool record belongs to an entity if one of its own string fields names it (or its FIPS/id)."""
    ids = {e["key"], *e["names"]}
    return any(isinstance(v, str) and v in ids for v in d.values())


def _index_numbers(value, catalog: list[dict], bound: dict, free: set) -> None:
    """Split tool-output numbers into per-entity records (bound) and non-entity fields (free)."""
    if isinstance(value, list):
        for v in value:
            _index_numbers(v, catalog, bound, free)
    elif isinstance(value, dict):
        owners = [e["key"] for e in catalog if _binds(value, e)]
        if owners:
            nums = _numbers_in_output(value)
            for k in owners:
                bound.setdefault(k, set()).update(nums)
        else:
            for v in value.values():
                _index_numbers(v, catalog, bound, free)
    else:
        free.update(_numbers_in_output(value))


def check_numbers(answer: str, tool_outputs: list[dict], question: str,
                  catalog: list[dict] | None = None) -> Check:
    name = "numbers_match_tools"
    catalog = catalog or []
    everywhere = _numbers_in_output(tool_outputs)
    asked = _numbers_in_text(question)
    unmatched = sorted(n for n in _numbers_in_text(answer) if n not in everywhere | asked)
    if unmatched:
        shown = ", ".join(f"{n:g}" for n in unmatched)
        return Check(name, False, True, f"Numbers not found in any tool output: {shown}")

    bound, free = {}, set()
    _index_numbers(tool_outputs, catalog, bound, free)
    misattributed = []
    for clause in CLAUSE_SPLIT_RE.split(answer):
        named = _mentions(clause, catalog)
        if not named:
            continue  # nothing to bind to; the anywhere-check above already ran
        allowed = free | asked | set().union(*(bound.get(e["key"], set()) for e in named))
        for n in sorted(_numbers_in_text(clause) - allowed):
            owner = next((e["label"] for e in catalog if n in bound.get(e["key"], set())), "another entity")
            misattributed.append(f"{n:g} next to {', '.join(e['label'] for e in named)} belongs to {owner}")
    if misattributed:
        return Check(name, False, True, "Number attributed to the wrong place: " + "; ".join(misattributed))
    return Check(name, True, True, "Every number traces back to a tool output for the place it is next to")


def _strings_in_output(value) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(set(), *(_strings_in_output(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(set(), *(_strings_in_output(v) for v in value))
    return set()


def check_entities(answer: str, tool_outputs: list[dict], catalog: list[dict]) -> Check:
    name = "entities_match_tools"
    returned = _strings_in_output(tool_outputs)
    problems = []

    for e in _mentions(answer, catalog):
        if not ({e["key"], *e["names"]} & returned):
            problems.append(f"{e['label']} named but no tool returned it this turn")
    known = {n for e in catalog for n in e["names"]}
    for m in dict.fromkeys(COUNTY_MENTION_RE.findall(answer)):
        if m not in known and f"{m} County" not in known:
            problems.append(f"{m} County is not in any tool output")
    for m in dict.fromkeys(SHELTER_ID_RE.findall(answer)):
        if m not in known:
            problems.append(f"{m} is not in any tool output")

    # Absence needs evidence: an empty, successful shelter lookup for that county.
    empty_lookups = {o.get("county_fips") for o in tool_outputs if "shelters" in o and not o["shelters"]}
    for clause in CLAUSE_SPLIT_RE.split(answer):
        if not SHELTER_ABSENCE_RE.search(clause):
            continue
        counties = [e for e in _mentions(clause, catalog) if e["kind"] == "county"]
        for c in counties or [None]:
            if (c["key"] if c else None) not in empty_lookups and not (c is None and empty_lookups):
                where = c["label"] if c else "that area"
                problems.append(f'"no shelters" claim for {where} without an empty query_assets lookup for it')

    if problems:
        return Check(name, False, True, "; ".join(problems))
    return Check(name, True, True, "Every place and facility named came from a tool output")


def check_steps(answer: str, calls: list[str], tool_outputs: list[dict],
                order_calls: list[str] | None = None) -> Check:
    """calls: every call this turn (for "was solve_staging run at all").
    order_calls: the calls whose order matters (the latest attempt's, so a retry can fix it)."""
    problems = []
    order_calls = calls if order_calls is None else order_calls
    for i, name in enumerate(order_calls):
        if name in MODEL_TOOLS and "get_advisory" not in order_calls[:i + 1]:
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


def check_confidence(answer: str, tool_outputs: list[dict], catalog: list[dict] | None = None) -> Check:
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
    # Alias-aware ("Levy" as well as "Levy County"): models drop the suffix in tables.
    named = {e["key"] for e in _mentions(answer, catalog or [])}
    for c in impact["counties"] if impact else []:
        q = c["pct_customers_out"]
        mentioned = c["fips"] in named or c["name"] in answer
        if mentioned and float(q["median"]) in stated_pcts \
                and not {float(q["low"]), float(q["high"])} <= answer_nums:
            problems.append(f"{c['name']} outage given without its range ({q['low']:g}–{q['high']:g}%)")
    context = " and ".join(reasons)
    if problems:
        return Check(name, False, True, f"Forecast is uncertain ({context}) but the answer has: "
                     + "; ".join(problems) + ". State the range and drop certainty words")
    return Check(name, True, True, f"No certainty words; outage figures carry ranges ({context})")


def run_checks(answer: str, calls: list[str], tool_outputs: list[dict], question: str,
               catalog: list[dict], order_calls: list[str] | None = None) -> list[Check]:
    """Deterministic checks. The actionable judge runs separately, on the final answer only."""
    return [
        check_numbers(answer, tool_outputs, question, catalog),
        check_entities(answer, tool_outputs, catalog),
        check_steps(answer, calls, tool_outputs, order_calls),
        check_confidence(answer, tool_outputs, catalog),
    ]


def to_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]
