"""Dallas ADK agent + trust wrapper, in mock mode (no LLM, no network).

Regression cases at the bottom come from the first live Gemini run (2026-10-04).
"""

import os

import pytest

os.environ["DALLAS_LIVE_ALERTS"] = "off"

from agent import dallas_tools as T  # noqa: E402
from agent import trust  # noqa: E402
from agent.dallas_adk import build_agent, build_model, run_dallas_agent  # noqa: E402
from dallas import build, store  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (build.RAW / "dallas311").exists(),
    reason="raw Dallas data missing: python data/sync_cloud_data.py pull --dataset dallas",
)

QUESTIONS = {
    "How should we prepare for this storm?": ["get_storm_alert", "estimate_demand", "plan_response"],
    "What if we only have 30 trucks and Fair Park is closed?": ["get_storm_alert", "plan_response", "diff_plans"],
    "Has Dallas had a storm like this before?": ["get_storm_alert", "find_similar_storms"],
    "What happened during Winter Storm Uri?": ["get_storm_alert", "get_storm_impacts"],
    "Does El Niño matter this winter?": ["get_storm_alert", "get_enso_context", "find_similar_storms"],
    "What should residents do if the power goes out?": ["retrieve_guidance"],
}


@pytest.fixture(scope="module", autouse=True)
def tables():
    build.build()
    store.table.cache_clear()


@pytest.mark.parametrize("question, calls", QUESTIONS.items())
def test_demo_questions_pass_first_try(question, calls):
    r = run_dallas_agent(question, [], build_agent(build_model("mock")))
    assert r["status"] == "passed", r["attempts"]
    assert [c["name"] for c in r["tool_calls"]] == calls
    assert r["answer"] and r["sources"]
    judge = next(c for c in r["checks"] if c["name"] == "actionable")
    assert judge["passed"] is None and "Not configured" in judge["detail"]  # visible, not a silent pass


def test_what_if_arguments_reach_the_tools():
    r = run_dallas_agent("What if we only have 30 trucks and Fair Park is closed?", [], build_agent(build_model("mock")))
    args = {c["name"]: c["arguments"] for c in r["tool_calls"]}
    assert args["plan_response"] == {"trucks": 30, "unavailable_shelters": ["Fair Park"]} == args["diff_plans"]
    assert "760" in r["answer"]  # shortfall at median with Fair Park closed: 1200 - 440


def test_bare_median_is_blocked_then_regenerated():
    r = run_dallas_agent("How should we prepare?", [], build_agent(build_model("mock", bad_first=True)))
    assert r["status"] == "regenerated"
    first = {c["name"]: c["passed"] for c in r["attempts"][0]["checks"]}
    assert first["confidence_fits_lead_time"] is False


def test_history_is_replayed_into_the_session():
    hist = [{"role": "user", "content": "Has Dallas had a storm like this before?"},
            {"role": "assistant", "content": "Yes, the February 2023 ice storm was the closest."}]
    r = run_dallas_agent("What if we only have 30 trucks?", hist, build_agent(build_model("mock")))
    assert r["status"] == "passed"


def test_api_serves_dallas_by_default(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "mock")
    monkeypatch.setenv("JUDGE_MODEL", "")
    from fastapi.testclient import TestClient
    import app as app_mod
    assert app_mod.DOMAIN == "dallas"
    with TestClient(app_mod.app) as c:
        h = c.get("/api/health").json()
        assert h == {"model": "mock", "mock": True, "judge": None, "domain": "dallas"}
        r = c.post("/api/chat", json={"message": "How should we prepare for this storm?"}).json()
        assert r["status"] == "passed" and r["tool_calls"][0]["name"] == "get_storm_alert"


# ---- regressions from the live Gemini run ----

def test_district_names_are_not_read_as_numbers():
    alert, impacts = T.run_tool("get_storm_alert", {}), T.run_tool("get_storm_impacts", {"storm_id": "uri_2021"})
    top = impacts["top_districts"]
    answer = "Busiest areas: " + ", ".join(f"District {d['district']} ({d['storm_day_requests']} requests)" for d in top) + "."
    res = trust.run_checks(answer, ["get_storm_alert", "get_storm_impacts"], [alert, impacts],
                           "What happened during Winter Storm Uri?", T.entity_catalog(), profile=trust.DALLAS)
    assert all(c.passed is not False for c in res), [c.detail for c in res if c.passed is False]


def test_number_from_a_field_name_is_still_caught():
    alert, impacts = T.run_tool("get_storm_alert", {}), T.run_tool("get_storm_impacts", {"storm_id": "uri_2021"})
    res = trust.run_checks("Uri kept more than 10,000 customers out for 109.5 hours.", ["get_storm_alert", "get_storm_impacts"],
                           [alert, impacts], "What happened during Uri?", T.entity_catalog(), profile=trust.DALLAS)
    nums = next(c for c in res if c.name == "numbers_match_tools")
    assert nums.passed is False and "10000" in nums.detail
