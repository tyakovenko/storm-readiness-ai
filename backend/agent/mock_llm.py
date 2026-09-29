"""Scripted stand-in for an LLM, used when LLM_MODEL=mock.

It makes real tool calls (chosen by keywords) and writes its answer only from
the tool outputs, so the whole pipeline and trust layer run without an API key.
Trust demos (each misbehaves once, then the regenerate passes):
  "hallucinate"   -> invents a number (numbers_match_tools)
  "overconfident" -> certainty words and no ranges (confidence_fits_lead_time)
"""

import json
import re

from .llm import ToolCall, Turn
from .loop import TRUST_FEEDBACK_PREFIX


class MockLLM:
    model = "mock"

    def complete(self, messages: list[dict], tools: list[dict]) -> Turn:
        user_idxs = [i for i, m in enumerate(messages) if m["role"] == "user"]
        regenerating = messages[user_idxs[-1]]["content"].startswith(TRUST_FEEDBACK_PREFIX)
        q_idx = next(i for i in reversed(user_idxs)
                     if not messages[i]["content"].startswith(TRUST_FEEDBACK_PREFIX))
        question = messages[q_idx]["content"]

        results = _tool_results(messages[q_idx + 1:])
        if not results:
            return self._call_tools(question)
        q = question.lower()
        text = _compose(question, results,
                        hallucinate=not regenerating and "hallucinat" in q,
                        overconfident=not regenerating and "overconfident" in q)
        return Turn(text, [], {"role": "assistant", "content": text})

    def _call_tools(self, question: str) -> Turn:
        q = question.lower()
        calls = [("get_advisory", {})]
        wants_plan = any(w in q for w in ("truck", "stage", "staging", "generator", "resource",
                                          "plan", "shelter", "closed", "need"))
        wants_analogs = any(w in q for w in ("similar", "analog", "past", "history", "before"))
        wants_guidance = any(w in q for w in ("resident", "prepare", "guidance", "alert", "people"))
        wants_enso = any(w in q for w in ("el niño", "el nino", "enso", "la niña", "la nina", "season"))
        if wants_plan:
            args = {}
            if m := re.search(r"(\d+)\s+trucks?", q):
                args["max_trucks"] = int(m.group(1))
            closed = re.findall(r"shelter\s*(\d+)", q)
            if closed and any(w in q for w in ("closed", "unavailable", "out of", "down")):
                args["unavailable_sites"] = [f"Shelter {n}" for n in closed]
            calls += [("predict_impact", {}), ("solve_staging", args)]
            if args:
                calls.append(("diff_plans", args))
        if wants_enso:
            calls.append(("get_enso_context", {}))
        if wants_analogs:
            calls.append(("find_analogs", {}))
        if wants_guidance:
            calls.append(("retrieve_guidance", {"topic": question}))
        if len(calls) == 1:
            calls.append(("predict_impact", {}))

        tool_calls = [ToolCall(f"mock_{i}", name, args) for i, (name, args) in enumerate(calls)]
        raw = {"role": "assistant", "content": None, "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.arguments)}} for c in tool_calls]}
        return Turn("", tool_calls, raw)


def _tool_results(messages: list[dict]) -> dict:
    names = {}
    results = {}
    for m in messages:
        for tc in m.get("tool_calls") or []:
            names[tc["id"]] = tc["function"]["name"]
        if m["role"] == "tool":
            results[names[m["tool_call_id"]]] = json.loads(m["content"])
    return results


def _pct(q: dict) -> str:
    return f"{q['median']:g}% of customers out (range {q['low']:g}–{q['high']:g}%)"


def _compose(question: str, r: dict, hallucinate: bool, overconfident: bool = False) -> str:
    lines = []
    if a := r.get("get_advisory"):
        lines.append(f"{a['storm_name']}, advisory {a['advisory_number']}: Category {a['category']}, "
                     f"{a['max_wind_kt']} kt, landfall forecast on the {a['forecast_landfall']} "
                     f"in about {a['lead_time_to_landfall_h']} hours.")
    if imp := r.get("predict_impact"):
        lines.append("\nExpected power outages by county:")
        for c in imp["counties"]:
            if overconfident:
                lines.append(f"- {c['name']} will definitely lose power: "
                             f"{c['pct_customers_out']['median']:g}% of customers out")
            else:
                lines.append(f"- {c['name']} ({c['risk_tier']}): {_pct(c['pct_customers_out'])}")
    if s := r.get("solve_staging"):
        lines.append(f"\nStaging plan from {s['staging_area']} with {s['trucks_available']} trucks "
                     f"({s['method']}):")
        for al in s["allocations"]:
            lines.append(f"- {al['county']}: {al['truckloads_assigned']} of {al['truckloads_needed']} truckloads")
        if s["total_truckloads_unmet"]:
            lines.append(f"Unmet: {s['total_truckloads_unmet']} truckloads.")
        if s["shelters_closed"]:
            lines.append(f"Closed: {', '.join(s['shelters_closed'])}.")
        lines.append(f"Shelter beds open: {s['shelter_beds_available']}; estimated demand "
                     f"{s['shelter_demand_estimate']}; shortfall {s['shelter_bed_shortfall']}. "
                     f"({s['shelter_demand_assumption']})")
    if d := r.get("diff_plans"):
        lines.append(f"\nWhat changed versus the full plan ({d['baseline']['trucks_available']} trucks, "
                     f"{len(d['baseline']['shelters_closed'])} shelters closed):")
        for c in d["county_changes"]:
            lines.append(f"- {c['county']}: {c['truckloads_before']} → {c['truckloads_after']} truckloads")
        lines.append(f"- Unmet truckloads: {d['unmet_truckloads_before']} → {d['unmet_truckloads_after']}")
        lines.append(f"- Shelter beds: {d['shelter_beds_before']} → {d['shelter_beds_after']}; "
                     f"shortfall {d['shelter_bed_shortfall_before']} → {d['shelter_bed_shortfall_after']}")
    if e := r.get("get_enso_context"):
        lines.append(f"\nSeasonal context: {e['phase']} ({e['strength']}), ONI {e['oni_c']:g} °C "
                     f"for {e['season']} {e['year']}. This shifts seasonal odds, not this storm's forecast.")
    if an := r.get("find_analogs"):
        lines.append("\nMost similar past storms:")
        for x in an["analogs"]:
            lines.append(f"- {x['storm']} ({x['year']}, {x['enso_phase']}): similarity {x['similarity']:g}, "
                         f"median peak outage {x['peak_pct_customers_out_median']:g}%")
    if g := r.get("retrieve_guidance"):
        lines.append("\nGuidance for residents:")
        lines += [f"- {t}" for t in g["snippets"]]
    if hallucinate:
        lines.append("\nExpect roughly 37% more outages than the last storm.")
    lines.append("\nNote: all figures are demo stub data.")
    return "\n".join(lines)
