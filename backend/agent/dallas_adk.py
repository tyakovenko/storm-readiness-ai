"""Dallas agent on Google ADK, wrapped by the trust layer.

    question -> ADK agent (Gemini / mock) calls Dallas tools -> answer
             -> trust checks (DALLAS profile) -> pass: show
             -> fail: feedback in the same session, one regenerate -> fail again: block

Trust runs here, around the ADK run, not in ADK callbacks: the checks need all
of the turn's tool outputs and must be able to ask for a rewrite (decision
2026-10-04). Response shape matches loop.run_agent so the UI is unchanged.
"""

from __future__ import annotations

import logging

from google.adk.agents.llm_agent import Agent

from . import trust
from .adk_runner import check_model, model_from_name, model_label, run_with_trust  # noqa: F401  (re-exported for app.py)
from .dallas_mock import MockDallasLlm
from .dallas_tools import entity_catalog, run_tool

log = logging.getLogger(__name__)

INSTRUCTION = """You are the Dallas Storm Readiness assistant. You help City of Dallas \
emergency managers prepare for a winter storm: what past storms broke, how much demand to \
expect, and where to send sanding trucks and shelter capacity.

Rules:
- Answer first: your first sentence directly answers the question - the recommendation, the yes/no, or \
the estimate with its range. Details, the scenario note and context come after it, never before.
- Never calculate, estimate or invent numbers: no sums, differences, counts ("13 districts") or \
rounding. Every number, place, district, shelter and storm you mention must come from a tool \
result in this conversation, written exactly as the tool gives it. If no tool gives it, say so.
- In every turn, call get_storm_alert first. If its kind is "scenario", say briefly, right after \
your first sentence, that it is a planning scenario, not a real alert.
- For trucks, shelters, staffing or "what should we do", call plan_response. Turn what-ifs into \
its arguments ("only 30 trucks" -> trucks=30; "Fair Park is closed" -> unavailable_shelters=["Fair Park"]) \
and also call diff_plans with the same arguments, then say what changed.
- For demand ("how many people", "how bad"), call estimate_demand. Whenever you mention an estimate \
(shelter demand, requests, outages), write it as "<low> to <high> (median <median>, from <n> past storms)" filled in with the tool's numbers. Never use certainty words \
(definitely, certainly, will lose power) before the storm.
- For "has this happened before", call find_similar_storms; for one storm's details, get_storm_impacts.
- For El Niño or the season, call get_enso_context. El Niño shifts seasonal odds; it never forecasts \
a specific storm. No past Dallas storm in the data happened under El Niño - say so when it matters.
- For advice to residents, call retrieve_guidance.
- Name council districts as "District N". Be brief: a few sentences or a short list. Plain language.
- Keep each storm's and each district's numbers in their own sentence or list item: never put the \
scenario's figures, or another district's, in the same sentence as a named past storm or district.
- End informational answers with one line on what it means for the plan (which district, shelter or kind of \
demand it affects), using only tool numbers. Mention trucks, staging or allocation only if you called \
plan_response this turn; for history questions, name the demand (e.g. transport requests), not trucks."""


# ---- tools as ADK sees them (typed signatures -> function declarations) ----

def get_storm_alert() -> dict:
    """Get the winter storm alert for Dallas County: live NWS alert if active, otherwise the labeled
    planning scenario (ice, minimum temperature, hours below freezing, snow, lead time). Call first."""
    return run_tool("get_storm_alert", {})


def find_similar_storms(ice_accretion_in: float | None = None, min_temp_f: float | None = None,
                        hours_below_freezing: float | None = None, snowfall_in: float | None = None) -> dict:
    """Rank past Dallas winter storms by weather similarity to this storm, with what each caused
    (peak power outages, 311 surges by sector). Amounts default to the alert's.

    Args:
        ice_accretion_in: Forecast ice accretion in inches.
        min_temp_f: Forecast minimum temperature in F.
        hours_below_freezing: Forecast hours below 32 F.
        snowfall_in: Forecast snow/sleet in inches.
    """
    args = {k: v for k, v in dict(ice_accretion_in=ice_accretion_in, min_temp_f=min_temp_f,
                                   hours_below_freezing=hours_below_freezing, snowfall_in=snowfall_in).items()
            if v is not None}
    return run_tool("find_similar_storms", args)


def get_storm_impacts(storm_id: str) -> dict:
    """Details of one past storm: weather, outages, 311 surges, busiest council districts, NOAA
    narrative, FEMA aid, what the city deployed.

    Args:
        storm_id: One of uri_2021, ice_2023, winter_2025, fern_2026, harvey_2017.
    """
    return run_tool("get_storm_impacts", {"storm_id": storm_id})


def estimate_demand() -> dict:
    """Demand for this storm as low/median/high ranges from the most similar past storms: shelter
    guests per day, storm-driven street 311 requests, peak outages, requests per council district."""
    return run_tool("estimate_demand", {})


def query_assets() -> dict:
    """Dallas response assets: inclement weather shelters with capacity, sanding trucks, field staff,
    department headcounts (FTE), shelter history, FEMA evacuee shelter capacity."""
    return run_tool("query_assets", {})


def _what_if(trucks, unavailable_shelters) -> dict:
    return {k: v for k, v in dict(trucks=trucks, unavailable_shelters=unavailable_shelters).items() if v is not None}


def plan_response(trucks: int | None = None, unavailable_shelters: list[str] | None = None) -> dict:
    """Response plan: sanding trucks per council district and shelter beds vs demand.

    Args:
        trucks: Sanding trucks available, if the user limits them (default 50).
        unavailable_shelters: Shelters that can't open, by id or name, e.g. ["Fair Park"].
    """
    return run_tool("plan_response", _what_if(trucks, unavailable_shelters))


def diff_plans(trucks: int | None = None, unavailable_shelters: list[str] | None = None) -> dict:
    """Compare a what-if plan with the default plan: districts that gain or lose trucks, and how
    shelter beds and shortfall change. Use the same arguments as plan_response.

    Args:
        trucks: Sanding trucks available under the what-if.
        unavailable_shelters: Shelters closed under the what-if.
    """
    return run_tool("diff_plans", _what_if(trucks, unavailable_shelters))


def get_enso_context() -> dict:
    """Current El Niño / La Niña state (NOAA Oceanic Niño Index) for seasonal context."""
    return run_tool("get_enso_context", {})


def retrieve_guidance(topic: str) -> dict:
    """Official winter safety guidance for residents (NWS, City of Dallas).

    Args:
        topic: What the guidance should cover.
    """
    return run_tool("retrieve_guidance", {"topic": topic})


ADK_TOOLS = [get_storm_alert, find_similar_storms, get_storm_impacts, estimate_demand, query_assets,
             plan_response, diff_plans, get_enso_context, retrieve_guidance]


# ---- model + agent (shared runner in adk_runner.py) ----

def build_model(name: str | None = None, bad_first: bool = False):
    """LLM_MODEL: "mock" | a Gemini id (Vertex, via ADC) | a LiteLLM string with "/" (e.g. anthropic/...)."""
    return model_from_name(name, lambda: MockDallasLlm(bad_first=bad_first))


def build_agent(model) -> Agent:
    return Agent(model=model, name="dallas_storm_agent", instruction=INSTRUCTION, tools=ADK_TOOLS,
                 description="Dallas winter storm readiness: past impacts, demand ranges, truck and shelter plans.")


def run_dallas_agent(question: str, history: list[dict], agent: Agent, judge=None) -> dict:
    return run_with_trust(question, history, agent, judge, trust.DALLAS, entity_catalog())
