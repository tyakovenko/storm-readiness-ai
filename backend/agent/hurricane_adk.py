"""Hurricane county agents on ADK (template x pack), wrapped by the shared trust runner.

One agent per county pack: the tools are closures over that county's HurricaneToolset, so the
model never chooses a county. build_county_agent(fips, model) -> (agent, toolset).
"""

from __future__ import annotations

import re
from typing import AsyncGenerator

from google.adk.agents.llm_agent import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from . import trust
from .adk_runner import TRUST_PREFIX, model_from_name, run_with_trust
from .hurricane_tools import HurricaneToolset

INSTRUCTION = """You are the {county} Hurricane Readiness assistant. You help {county} emergency \
managers prepare for a hurricane: expected power outages, what past storms did here, and shelter capacity.

Rules:
- Never calculate, estimate or invent numbers: no sums, differences, counts or rounding. Every number, \
place, shelter and storm you mention must come from a tool result in this conversation, written exactly as given.
- In every turn, call get_storm_alert first. Its kind is "replay": say briefly that this is a real past \
forecast replayed for practice, not a live storm.
- For outages or "how bad", call estimate_impact. Write the estimate as "LOW to HIGH (median MEDIAN)" with \
its unit, and mention the model's tested skill once in plain words (e.g. "on storms it never saw, it was off by \
MAE points on average"), never as raw field names. Never use certainty words (definitely, certainly, will \
lose power) before landfall.
- For shelters, call query_assets and plan_shelters. For a what-if ("X shelter is closed", "include surge-zone \
sites") call plan_shelters and diff_plans with the same arguments and say what changed. Shelter demand is not \
available - say so if asked.
- For "has this happened before", call find_similar_storms; for one storm's details, get_storm_impacts.
- For El Niño or the season, call get_enso_context; for advice to residents, retrieve_guidance.
- Be brief: a few sentences or a short list. End informational answers with one line on what it means for \
the plan, using only tool numbers."""


def _tools_for(ts: HurricaneToolset) -> list:
    """Typed wrappers (ADK builds function declarations from signatures + docstrings)."""

    def get_storm_alert() -> dict:
        """Get the hurricane alert for this county: a real NHC forecast replayed for practice (or a live one),
        with lead time, forecast closest approach, estimated wind at the county and side of track. Call first."""
        return ts.run_tool("get_storm_alert", {})

    def find_similar_storms() -> dict:
        """Past storms (since 2014) that passed within 150 nm of this county, ranked by similarity to this
        forecast, with their real peak power outages."""
        return ts.run_tool("find_similar_storms", {})

    def generate_scenarios() -> dict:
        """Get the spread of possible storm tracks around the official forecast using an AR(1) error model."""
        return ts.run_tool("generate_scenarios", {})

    def estimate_impact() -> dict:
        """Trained outage model estimate for this county: low/median/high % of customers out and customers
        out, top drivers, and the model's skill on storms it never saw."""
        return ts.run_tool("estimate_impact", {})

    def get_storm_impacts(storm_id: str) -> dict:
        """Details of one past storm in this county: wind and distance, peak outages, NOAA events, FEMA aid.

        Args:
            storm_id: e.g. AL092022 (from find_similar_storms).
        """
        return ts.run_tool("get_storm_impacts", {"storm_id": storm_id})

    def query_assets() -> dict:
        """FEMA shelters in this county: totals, capacity outside surge zones and floodplains, pet-friendly,
        generators, the largest sites, and known data gaps."""
        return ts.run_tool("query_assets", {})

    def plan_shelters(unavailable_shelters: list[str] | None = None, exclude_surge_and_floodplain: bool = True) -> dict:
        """Shelter plan: beds at open shelters, by default excluding surge-zone and floodplain sites.

        Args:
            unavailable_shelters: Shelters that can't open, by name.
            exclude_surge_and_floodplain: Leave out surge-zone and 100-yr floodplain sites (default true).
        """
        args = {"exclude_surge_and_floodplain": exclude_surge_and_floodplain}
        if unavailable_shelters:
            args["unavailable_shelters"] = unavailable_shelters
        return ts.run_tool("plan_shelters", args)

    def diff_plans(unavailable_shelters: list[str] | None = None, exclude_surge_and_floodplain: bool = True) -> dict:
        """Compare a what-if shelter plan with the default plan (beds before and after).

        Args:
            unavailable_shelters: Shelters closed under the what-if.
            exclude_surge_and_floodplain: Same meaning as in plan_shelters.
        """
        args = {"exclude_surge_and_floodplain": exclude_surge_and_floodplain}
        if unavailable_shelters:
            args["unavailable_shelters"] = unavailable_shelters
        return ts.run_tool("diff_plans", args)

    def get_enso_context() -> dict:
        """Current El Niño / La Niña state (NOAA Oceanic Niño Index)."""
        return ts.run_tool("get_enso_context", {})

    def retrieve_guidance(topic: str) -> dict:
        """Official hurricane safety guidance for residents (NWS / NHC).

        Args:
            topic: What the guidance should cover.
        """
        return ts.run_tool("retrieve_guidance", {"topic": topic})

    def save_plan(notes: str = "", author: str = "Emergency Manager") -> dict:
        """Save the current county resource deployment plan as a draft for review."""
        return ts.run_tool("save_plan", {"notes": notes, "author": author})

    def approve_plan(plan_id: str, approver: str = "Emergency Director", notes: str = "") -> dict:
        """Formally approve a staged deployment plan and record digital sign-off."""
        return ts.run_tool("approve_plan", {"plan_id": plan_id, "approver": approver, "notes": notes})

    return [get_storm_alert, find_similar_storms, generate_scenarios, estimate_impact, get_storm_impacts, query_assets, plan_shelters,
            diff_plans, get_enso_context, retrieve_guidance, save_plan, approve_plan]


# ---- scripted mock (LLM_MODEL=mock): answers only from tool outputs ----

def _n(v, nd=None) -> str:
    if v is None:
        return "unknown"
    v = float(v)
    if v.is_integer():
        return f"{int(v):,}"
    return f"{v:,.{nd}f}" if nd is not None else f"{v:g}"


def _plan_calls(q: str, ts: HurricaneToolset) -> list[tuple[str, dict]]:
    ql = q.lower()
    calls = [("get_storm_alert", {})]
    closed = [s["name"] for s in ts._shelters() if s["name"] and s["name"].lower() in ql]
    if closed or any(w in ql for w in ("what if", "closed", "unavailable", "can't open")):
        args = {"unavailable_shelters": closed} if closed else {}
        return calls + [("plan_shelters", args), ("diff_plans", args)]
    storm = next((s for s in ts._storms() if s["name"].split()[0].lower() in ql and s["name"].split()[-1] in ql), None)
    if storm:
        return calls + [("get_storm_impacts", {"storm_id": storm["storm_id"]})]
    if any(w in ql for w in ("el niño", "el nino", "enso", "season")):
        return calls + [("get_enso_context", {})]
    if any(w in ql for w in ("before", "similar", "past", "history")):
        return calls + [("find_similar_storms", {})]
    if any(w in ql for w in ("resident", "safety", "guidance", "tell people")):
        return [("retrieve_guidance", {"topic": q})]
    if "shelter" in ql:
        return calls + [("query_assets", {}), ("plan_shelters", {})]
    return calls + [("estimate_impact", {}), ("plan_shelters", {})]


def _compose(o: dict, bad: bool = False) -> str:
    L = []
    a = o.get("get_storm_alert")
    if a:
        side = "right (stronger) side" if a["right_of_track"] else "left side"
        L.append(f"This is a replay of a real past forecast, not a live storm: {a['headline'].removeprefix('REPLAY: ')}.")
        L.append(f"The forecast brings the center within {_n(a['forecast_closest_nm'])} nm of {a['county']}, "
                 f"with about {_n(a['forecast_wind_at_county_kt'])} kt estimated at the county on the {side}.")
    e = o.get("estimate_impact")
    if e:
        p, c, sk = e["pct_customers_out"], e["customers_out"], e["model_skill"]
        if bad:
            L.append(f"Expect about {_n(p['median'])}% of customers to lose power.")
        else:
            L.append(f"Model estimate: {_n(p['low'])}% to {_n(p['high'])}% of customers out (median {_n(p['median'])}%), "
                     f"{_n(c['low'])} to {_n(c['high'])} customers (median {_n(c['median'])}).")
        if "mae_median" in sk:
            L.append(f"On storms it never saw ({sk['tested_on'].split(',')[0]}), its median error was {_n(sk['mae_median'])} points.")
    s = o.get("find_similar_storms")
    if s:
        for x in s["storms"][:3]:
            L.append(f"- {x['name']} (similarity {_n(x['similarity'])}): peak {_n(x['peak_customers_out'])} customers out "
                     f"({_n(x['peak_pct_customers'])}%).")
    i = o.get("get_storm_impacts")
    if i:
        L.append(f"{i['name']} in {i['county']}: peak {_n(i['peak_customers_out'])} customers out "
                 f"({_n(i['peak_pct_customers'])}%), center {_n(i['dist_to_track_nm'])} nm away.")
    q = o.get("query_assets")
    if q:
        L.append(f"FEMA lists {_n(q['shelters_total'])} shelters in {q['county']} with {_n(q['evacuation_capacity_total'])} "
                 f"evacuation beds; {_n(q['with_generator'])} have a generator.")
    d = o.get("diff_plans")
    if d:
        L.append(f"What-if: beds go from {_n(d['beds_before'])} to {_n(d['beds_after'])}"
                 + (f" with {', '.join(d['shelters_removed'])} unavailable." if d["shelters_removed"] else "."))
    elif o.get("plan_shelters"):
        p = o["plan_shelters"]
        L.append(f"Shelter plan: {_n(p['shelters_open'])} shelters open outside surge zones and floodplains with "
                 f"{_n(p['beds_available'])} beds ({_n(p['beds_with_pets'])} take pets). Shelter demand is not available yet.")
    en = o.get("get_enso_context")
    if en:
        L.append(f"ENSO: ONI {_n(en['oni_c'])} for {en['season']} {en['year']}, {en['phase']} ({en['strength']}). "
                 "It shifts seasonal odds; it does not forecast a specific storm.")
    g = o.get("retrieve_guidance")
    if g:
        L += [f"- {t}" for t in g["snippets"]]
    return "\n".join(L) or "I couldn't find data for that. Ask about outages, shelters or past storms."


class MockHurricaneLlm(BaseLlm):
    model: str = "mock"
    bad_first: bool = False
    toolset: object = None

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents or []
        user_idx = [i for i, c in enumerate(contents) if c.role == "user" and any(p.text for p in c.parts or [])]
        last_user = user_idx[-1] if user_idx else -1
        question = next((p.text for c in (contents[i] for i in reversed(user_idx))
                         for p in c.parts if p.text and not p.text.startswith(TRUST_PREFIX)), "")
        feedback = bool(user_idx) and any((p.text or "").startswith(TRUST_PREFIX) for p in contents[last_user].parts)
        outputs = {}
        for c in contents:
            for p in c.parts or []:
                if p.function_response:
                    outputs[p.function_response.name] = p.function_response.response
        since = any(p.function_response for c in contents[last_user + 1:] for p in c.parts or [])
        if not since and not feedback:
            parts = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in _plan_calls(question, self.toolset)]
        else:
            demo = "trust demo" in question.lower()
            parts = [types.Part(text=_compose(outputs, bad=(self.bad_first or demo) and not feedback))]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


# ---- build + run ----

def build_county_agent(fips: str, model_name: str | None = None, bad_first: bool = False):
    ts = HurricaneToolset(fips)
    model = model_from_name(model_name, lambda: MockHurricaneLlm(bad_first=bad_first, toolset=ts))
    name = re.sub(r"\W", "_", ts.pack["slug"])
    agent = Agent(model=model, name=name, instruction=INSTRUCTION.format(county=ts.county), tools=_tools_for(ts),
                  description=f"{ts.county} hurricane readiness: outages, past storms, shelters.")
    return agent, ts


def run_county_agent(question: str, history: list[dict], agent, toolset: HurricaneToolset, judge=None) -> dict:
    return run_with_trust(question, history, agent, judge, trust.HURRICANE_COUNTY, toolset.entity_catalog())
