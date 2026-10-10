"""Deterministic routing for the landing-page Ask AI (AGENT_DOMAIN=multi, no storm selected yet).

/api/chat is only ever called from the home page, before a storm is open (once a storm is open,
the UI calls /api/agents/{id}/chat directly, which is already unambiguous). Before Phase 5,
/api/chat on "multi" always silently answered as the Dallas agent -- a hurricane question like
"which areas are highest risk" with no storm picked got a real-sounding Dallas answer, which is
wrong. This maps the question to a named scenario if one is named in it, and otherwise says
plainly that no storm is selected and lists what's available. No LLM call and no intent
classifier: just matching the question text against the registry's own names.
"""

from __future__ import annotations

import re

_WINTER_NAMES = ("dallas", "dallas county", "winter storm", "ice storm", "uri")


def _names_for(agent: dict) -> set[str]:
    """Every string a user might type to mean this agent, lowercased."""
    names = set()
    county = agent.get("county")
    if county:
        names.add(county.lower())
        names.add(county.replace(" County", "").replace(" county", "").lower())
    replay = agent.get("replay")
    if replay:
        names.add(replay.lower())
        names.add(f"hurricane {replay}".lower())
        names.add(f"tropical storm {replay}".lower())
    if agent.get("hazard") == "winter":
        names.update(_WINTER_NAMES)
    return {n for n in names if n}


def scenario_for(question: str, agents: list[dict]) -> dict | None:
    """The county replay scenario (or Dallas) a question names, if any."""
    live = [a for a in agents if not str(a.get("status", "")).startswith("error")]
    by_name: dict[str, dict] = {}
    for a in live:
        for n in _names_for(a):
            by_name[n] = a
    ql = question.lower()
    # Longest name first: "Miami-Dade County" must win over a shorter substring collision.
    for name in sorted(by_name, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", ql):
            return by_name[name]
    return None


def route(question: str, agents: list[dict]) -> dict:
    """{'kind': 'agent', 'agent_id': ...} if the question asks about the storms NHC is tracking now (the
    live agent) or names a replay scenario, else {'kind': 'none', 'agents': [...available scenarios...]}."""
    from .live_adk import is_live_question
    from .registry import LIVE_ID
    if is_live_question(question):
        return {"kind": "agent", "agent_id": LIVE_ID}
    match = scenario_for(question, agents)
    if match:
        return {"kind": "agent", "agent_id": match["id"]}
    return {"kind": "none", "agents": [a for a in agents if not str(a.get("status", "")).startswith("error")]}


def _describe(agent: dict) -> str:
    place = f"{agent['county']}{', ' + agent['state'] if agent.get('state') else ''}"
    if agent.get("hazard") == "winter":
        return f"{place} (winter storm planning scenario)"
    if agent.get("replay"):
        return f"{place} (Hurricane {agent['replay']} replay)"
    return f"{place} (hurricane)"


def no_storm_selected_response(agents: list[dict]) -> dict:
    """Same response shape run_with_trust returns, so the existing Ask AI panel renders it
    with no special-casing. status 'passed' because nothing was blocked -- there's just
    nothing county-specific to say yet."""
    options = "; ".join(_describe(a) for a in agents)
    answer = (
        "No storm or county is selected yet, so I can't give an area-specific answer. "
        'For the storms happening now, just ask (e.g. "Which storms are active right now?"). '
        f"Past-storm scenarios: {options}. Open one from the home page, or name it here "
        '(e.g. "Dallas" or "Hurricane Beryl in Harris County") and I\'ll answer for that one.'
    )
    return {
        "status": "passed", "answer": answer, "checks": [], "attempts": [{"text": answer, "checks": []}],
        "tool_calls": [], "sources": [], "why": [], "model": "router",
    }
