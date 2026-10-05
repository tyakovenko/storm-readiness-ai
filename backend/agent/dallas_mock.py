"""Scripted stand-in for Gemini inside ADK (LLM_MODEL=mock): free demos and tests.

Turn 1: pick tools from keywords in the question. Turn 2: write the answer only
from the tool outputs in the conversation, so it passes the trust checks the
same way a careful model would. It never invents a number.

bad_first=True makes the first answer quote a median without its range, so
tests can see the trust layer block it and the retry fix it.
"""

from __future__ import annotations

import re
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from .adk_runner import TRUST_PREFIX  # noqa: E402  (shared feedback marker)
TRUCKS_RE = re.compile(r"(\d+)\s+(?:sanding\s+)?trucks?", re.IGNORECASE)
CLOSED_RE = re.compile(r"(fair park|austin street|oak lawn)[^.?!]*?\b(closed|unavailable|can'?t open|not available|down)\b"
                       r"|\b(closed|unavailable|without|lose|lost)\b[^.?!]*?(fair park|austin street|oak lawn)", re.IGNORECASE)
STORM_KEYS = {"uri": "uri_2021", "fern": "fern_2026", "2023": "ice_2023", "january 2025": "winter_2025",
              "harvey": "harvey_2017"}


def _n(v) -> str:
    """Format a number the way it appears in the tool output (1200.0 -> 1,200; 0.79 -> 0.79)."""
    if v is None:
        return "unknown"
    v = float(v)
    return f"{int(v):,}" if v.is_integer() else f"{v:g}"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _plan_args(q: str) -> dict:
    args = {}
    m = TRUCKS_RE.search(q)
    if m:
        args["trucks"] = int(m.group(1))
    closed = []
    for m in CLOSED_RE.finditer(q):
        site = (m.group(1) or m.group(4) or "").lower()
        closed.append({"fair park": "Fair Park", "austin street": "Austin Street", "oak lawn": "Oak Lawn"}[site])
    if closed:
        args["unavailable_shelters"] = sorted(set(closed))
    return args


def plan_calls(question: str) -> list[tuple[str, dict]]:
    q = question.lower()
    calls = [("get_storm_alert", {})]
    what_if = _plan_args(question)
    if what_if and any(w in q for w in ("what if", "only", "closed", "unavailable", "lose", "without", "can't")):
        return calls + [("plan_response", what_if), ("diff_plans", what_if)]
    storm = next((sid for k, sid in STORM_KEYS.items() if k in q), None)
    if storm:
        return calls + [("get_storm_impacts", {"storm_id": storm})]
    if any(w in q for w in ("el niño", "el nino", "enso", "season", "winter outlook")):
        return calls + [("get_enso_context", {}), ("find_similar_storms", {})]
    if any(w in q for w in ("similar", "past", "history", "before", "like this")):
        return calls + [("find_similar_storms", {})]
    if any(w in q for w in ("resident", "safety", "guidance", "tell people", "advice for")):
        return [("retrieve_guidance", {"topic": question})]
    return calls + [("estimate_demand", {}), ("plan_response", {})]


def _range(r: dict, unit: str) -> str:
    return f"{_n(r['low'])} to {_n(r['high'])} {unit} (median {_n(r['median'])}, from {r['n']} past storms)"


def compose(outputs: dict[str, dict], bad: bool = False) -> str:
    lines = []
    alert = outputs.get("get_storm_alert")
    if alert:
        lead = "This is a planning scenario, not a real alert. " if alert["kind"] == "scenario" else ""
        lines.append(f"{lead}{_cap(alert['headline'].removeprefix('SCENARIO (not a real alert): '))}, "
                     f"onset {alert['onset_local']}.")
    if "diff_plans" in outputs:
        d = outputs["diff_plans"]
        w = d["what_if"]
        closed = ", ".join(w["shelters_closed"]) or "none"
        lines.append(f"What-if: {w['trucks_available']} trucks, shelters closed: {closed}.")
        for c in d["district_changes"][:4]:
            verb = "loses" if c["change"] < 0 else "gains"
            lines.append(f"- District {c['district']} {verb} {abs(c['change'])} trucks ({c['trucks_before']} to {c['trucks_after']}).")
        lines.append(f"Known shelter beds go from {_n(d['shelter_beds_before'])} to {_n(d['shelter_beds_after'])}; "
                     f"shortfall at median demand goes from {_n(d['shelter_shortfall_at_median_before'])} "
                     f"to {_n(d['shelter_shortfall_at_median_after'])}.")
    elif "plan_response" in outputs:
        p = outputs["plan_response"]
        top = p["truck_allocation"][:2]
        lines.append(f"With {p['trucks_available']} trucks, District {top[0]['district']} gets {top[0]['trucks']} trucks and "
                     f"District {top[1]['district']} gets {top[1]['trucks']} trucks (most past winter street requests).")
        dem = p["shelter_demand"]
        if bad:
            lines.append(f"Expect about {_n(dem['median'])} people per day at shelters.")
        elif dem:
            lines.append(f"Shelter demand from past storms: {_range(dem, 'people per day')}.")
        lines.append(f"Known beds at open shelters: {_n(p['shelter_beds_known'])}; shortfall at the median is "
                     f"{_n(p['shelter_shortfall_at_median'])}, at the high end {_n(p['shelter_shortfall_at_high'])}.")
        if p["shelters_unknown_capacity"]:
            lines.append(f"No published capacity for: {', '.join(p['shelters_unknown_capacity'])}.")
    if "estimate_demand" in outputs:
        e = outputs["estimate_demand"]
        lines.append(f"Storm-driven street requests (sanding, signals): {_range(e['transport_requests_storm_days'], 'requests')}.")
    if "find_similar_storms" in outputs:
        s = outputs["find_similar_storms"]
        for x in s["storms"][:3]:
            out = f"peak {_n(x['peak_customers_out'])} customers without power" if x["peak_customers_out"] is not None \
                else "no outage record"
            lines.append(f"- {x['name']} (similarity {_n(x['similarity'])}): {out}.")
        lines.append("None of these storms happened in an El Niño winter, so treat them as a rough guide.")
    if "get_enso_context" in outputs:
        e = outputs["get_enso_context"]
        lines.append(f"ENSO: ONI {_n(e['oni_c'])} for {e['season']} {e['year']}, {e['phase']} ({e['strength']}). "
                     "El Niño shifts seasonal odds toward a wet winter; it does not forecast a specific storm.")
    if "get_storm_impacts" in outputs:
        i = outputs["get_storm_impacts"]
        o = i["outages"]
        if o:
            lines.append(f"{i['name']}: peak {_n(o['peak_customers_out'])} customers without power "
                         f"({_n(o['peak_pct_customers'])}%).")
        else:
            lines.append(f"{i['name']}: no outage record for this storm.")
        for s in i["surges_311"][:2]:
            lines.append(f"- 311 '{s['request_type']}': {_n(s['storm_days_count'])} requests vs "
                         f"{_n(s['expected_count'])} expected.")
    if "retrieve_guidance" in outputs:
        lines += [f"- {t}" for t in outputs["retrieve_guidance"]["snippets"]]
    return "\n".join(lines) or "I couldn't find data for that. Try asking about the storm plan, shelters or past storms."


class MockDallasLlm(BaseLlm):
    model: str = "mock"
    bad_first: bool = False

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents or []
        user_idx = [i for i, c in enumerate(contents) if c.role == "user" and any(p.text for p in c.parts or [])]
        last_user = user_idx[-1] if user_idx else -1
        question = next((p.text for c in (contents[i] for i in reversed(user_idx))
                         for p in c.parts if p.text and not p.text.startswith(TRUST_PREFIX)), "")
        feedback = bool(user_idx) and any((p.text or "").startswith(TRUST_PREFIX) for p in contents[last_user].parts)
        responses = {}
        for c in contents:
            for p in c.parts or []:
                if p.function_response:
                    responses[p.function_response.name] = p.function_response.response
        since_question = any(p.function_response for c in contents[last_user + 1:] for p in c.parts or [])
        if not since_question and not feedback:
            parts = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in plan_calls(question)]
        else:
            # First real answer is "bad" in bad_first mode; the retry after feedback is clean.
            demo = "trust demo" in question.lower()  # UI demo button: misbehave once, then fix
            text = compose(responses, bad=(self.bad_first or demo) and not feedback)
            parts = [types.Part(text=text)]
        yield LlmResponse(content=types.Content(role="model", parts=parts))
