"""Agent registry for the multi-agent service (AGENT_DOMAIN=multi).

Agents = hazard template x county pack:
  dallas-winter          winter template (backend/dallas, agent/dallas_*)       - existing Dallas agent
  <slug> per pack        hurricane template (agent/hurricane_*), packs from hurricane/store.index()

Agents are built lazily on first use and cached; a broken pack fails that agent only, visibly.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

DALLAS = {"id": "dallas-winter", "name": "Dallas County winter storm", "hazard": "winter", "county": "Dallas County",
          "state": "TX", "fips": "48113", "status": "live"}

LIVE_ID = "live-storms"  # agent/live_adk.py: the storms NHC is tracking now

_lock = threading.Lock()
_agents: dict[str, tuple] = {}


def list_agents() -> list[dict]:
    from hurricane import store
    out = [dict(DALLAS)]
    try:
        for p in store.index():
            out.append({"id": p["slug"], "name": f"{p['county']} hurricane", "hazard": "hurricane", "county": p["county"],
                        "state": p["state"], "fips": p["fips"], "status": p["status"], "replay": p.get("replay"),
                        "storms": p.get("storms"), "shelters": p.get("shelters")})
    except Exception as e:  # no packs published: Dallas still works, the gap is visible in the list
        log.error("hurricane pack index unavailable: %s", e)
        out.append({"id": "hurricane-packs", "name": "Hurricane packs unavailable", "hazard": "hurricane",
                    "status": f"error: {e}"})
    return out


def get(agent_id: str, model_name: str | None = None):
    """(kind, agent, toolset_or_None) for an agent id. Raises KeyError for an unknown id."""
    with _lock:
        if agent_id in _agents:
            return _agents[agent_id]
        if agent_id == LIVE_ID:  # not a county card, so not in list_agents()
            from agent.live_adk import build_live_agent
            _agents[agent_id] = ("live", *build_live_agent(model_name))
            return _agents[agent_id]
        meta = next((a for a in list_agents() if a["id"] == agent_id), None)
        if meta is None or str(meta.get("status", "")).startswith("error"):
            raise KeyError(agent_id)
        if meta["hazard"] == "winter":
            from agent.dallas_adk import build_agent, build_model
            built = ("winter", build_agent(build_model(model_name)), None)
        else:
            from agent.hurricane_adk import build_county_agent
            agent, ts = build_county_agent(meta["fips"], model_name)
            built = ("hurricane", agent, ts)
        _agents[agent_id] = built
        return built


def chat(agent_id: str, question: str, history: list[dict], judge=None) -> dict:
    from agent.landing_router import scenario_for
    from agent.live_adk import is_live_question, names_active_storm, run_live_agent
    # A question about a storm NHC is tracking now goes to the live agent from any page; the open
    # county's scenario is a replay and can't answer it. The reverse too: on the live page, a question
    # naming a replay scenario (and no active storm) goes to that county's replay agent.
    if agent_id != LIVE_ID and is_live_question(question, strict=True):
        agent_id, history = LIVE_ID, []
    elif agent_id == LIVE_ID and not names_active_storm(question):
        replay = scenario_for(question, list_agents())
        if replay:
            agent_id, history = replay["id"], []
    kind, agent, ts = get(agent_id)
    if kind == "live":
        return run_live_agent(question, history, agent, ts, judge)
    if kind == "winter":
        from agent.dallas_adk import run_dallas_agent
        return run_dallas_agent(question, history, agent, judge)
    from agent.hurricane_adk import run_county_agent
    return run_county_agent(question, history, agent, ts, judge)


def storm_overview(slug: str, horizon_h: int | None = None) -> dict:
    """Storm-wide, multi-county Risk Map data for an existing hurricane pack's replayed storm
    (Phase 1). Raises KeyError for an unknown slug, ValueError for an unsupported horizon_h."""
    from . import storm_view
    return storm_view.build_storm_overview(slug, horizon_h)


def hurricane_overview(agent_id: str, closed: list[str], include_surge: bool, horizon_h: int | None = None) -> dict:
    """Dashboard data for a hurricane county agent: the same tools the agent calls, no LLM.

    horizon_h (Phase 2A): when the Risk Map's shared horizon selection is present, the outage
    panel shows that same forecast-valid-time prediction instead of its default peak/closest-
    approach snapshot, so Storm Overview and Risk Map agree for the same storm/county/horizon.
    Raises ValueError (via storm_view) for a horizon this storm's advisory has no point at."""
    from hurricane import store
    kind, _, ts = get(agent_id)
    if kind != "hurricane":
        raise KeyError(agent_id)
    what_if = {"exclude_surge_and_floodplain": not include_surge}
    if closed:
        what_if["unavailable_shelters"] = closed
    plan = ts.run_tool("plan_shelters", what_if)
    if horizon_h is not None:
        from . import storm_view
        impact = storm_view.county_impact_at_horizon(agent_id, horizon_h)
    else:
        impact = ts.run_tool("estimate_impact", {})
    return {
        "domain": "hurricane", "agent_id": agent_id, "county": ts.county, "fips": ts.fips,
        "alert": ts.run_tool("get_storm_alert", {}),
        "impact": impact,
        "similar": ts.run_tool("find_similar_storms", {}),
        "assets": ts.run_tool("query_assets", {}),
        "plan": plan,
        "diff": ts.run_tool("diff_plans", what_if) if (closed or include_surge) else None,
        "enso": ts.run_tool("get_enso_context", {}),
        "shelters": store.table(ts.fips, "assets.json")["shelters"],
        "storms": store.table(ts.fips, "storms.json")["storms"],
        "fema": store.table(ts.fips, "storms.json")["fema"],
        "geo": store.table(ts.fips, "geo.geojson"),
        "profile": ts.pack["profile"],
        "gaps": ts.pack["gaps"],
    }
