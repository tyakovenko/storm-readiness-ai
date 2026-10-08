"""Phase 5: the landing-page Ask AI's deterministic router (agent/landing_router.py).

Before Phase 5, /api/chat on AGENT_DOMAIN=multi always ran the Dallas agent, even for a
hurricane-flavored question with no storm selected. These tests exercise the router in
isolation (no LLM, no FastAPI) against the same registry data the real app uses.
"""

import pytest

from agent import landing_router, registry

try:
    AGENTS = registry.list_agents()
except Exception as e:  # no hurricane packs published: router tests need at least Dallas
    AGENTS = [dict(registry.DALLAS)]

HURRICANE_AGENTS = [a for a in AGENTS if a.get("hazard") == "hurricane" and not str(a.get("status", "")).startswith("error")]


def test_generic_hurricane_question_does_not_silently_pick_dallas():
    """Part G: "which areas are highest risk" names no scenario -- must not become a hidden
    Dallas answer."""
    routed = landing_router.route("Which areas are highest risk?", AGENTS)
    assert routed["kind"] == "none"
    resp = landing_router.no_storm_selected_response(routed["agents"])
    assert resp["status"] == "passed"
    assert "Dallas" not in resp["answer"] or "scenarios" in resp["answer"].lower()
    assert "No storm or county is selected" in resp["answer"]


def test_dallas_named_explicitly_still_routes_to_dallas():
    routed = landing_router.route("How should Dallas prepare for this storm?", AGENTS)
    assert routed == {"kind": "agent", "agent_id": "dallas-winter"}


@pytest.mark.skipif(not HURRICANE_AGENTS, reason="no hurricane packs published")
def test_named_hurricane_county_routes_to_that_agent():
    a = HURRICANE_AGENTS[0]
    routed = landing_router.route(f"What's the risk in {a['county']}?", AGENTS)
    assert routed == {"kind": "agent", "agent_id": a["id"]}


@pytest.mark.skipif(not any(a.get("replay") for a in HURRICANE_AGENTS), reason="no replay storm name published")
def test_named_storm_routes_to_its_county_agent():
    a = next(a for a in HURRICANE_AGENTS if a.get("replay"))
    routed = landing_router.route(f"Tell me about Hurricane {a['replay']}", AGENTS)
    assert routed == {"kind": "agent", "agent_id": a["id"]}


def test_no_storm_selected_response_lists_every_live_scenario():
    resp = landing_router.no_storm_selected_response(AGENTS)
    for a in AGENTS:
        if not str(a.get("status", "")).startswith("error"):
            assert a["county"] in resp["answer"]


def test_unknown_scenario_name_does_not_crash():
    routed = landing_router.route("", AGENTS)
    assert routed["kind"] == "none"


def test_existing_dallas_chat_still_works_through_the_registry():
    """Part L #12: unaffected by the Phase 5 router, which only gates /api/chat with no agent."""
    r = registry.chat("dallas-winter", "How should we prepare for this storm?", [], None)
    assert r["status"] in ("passed", "regenerated")


@pytest.mark.skipif(not HURRICANE_AGENTS, reason="no hurricane packs published")
def test_existing_hurricane_county_chat_still_works_through_the_registry():
    """Part L #13: unaffected by the Phase 5 router, which only gates /api/chat with no agent."""
    a = HURRICANE_AGENTS[0]
    r = registry.chat(a["id"], "How bad could the power outages be?", [], None)
    assert r["status"] in ("passed", "regenerated")
