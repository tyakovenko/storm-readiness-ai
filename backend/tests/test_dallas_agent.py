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


def test_outage_threshold_is_a_citable_value_and_other_thresholds_are_not():
    # Live run: Gemini read "10,000" out of the old key name hours_over_10k_out. The threshold is
    # now a value (threshold_customers_out), so 10,000 is citable; an invented threshold is not.
    alert, impacts = T.run_tool("get_storm_alert", {}), T.run_tool("get_storm_impacts", {"storm_id": "uri_2021"})
    calls, q = ["get_storm_alert", "get_storm_impacts"], "What happened during Uri?"
    ok = trust.run_checks("Winter Storm Uri kept more than 10,000 customers out for 109.5 hours.", calls,
                          [alert, impacts], q, T.entity_catalog(), profile=trust.DALLAS)
    assert next(c for c in ok if c.name == "numbers_match_tools").passed is True
    bad = trust.run_checks("Winter Storm Uri kept more than 20,000 customers out for 109.5 hours.", calls,
                           [alert, impacts], q, T.entity_catalog(), profile=trust.DALLAS)
    nums = next(c for c in bad if c.name == "numbers_match_tools")
    assert nums.passed is False and "20000" in nums.detail


def test_computed_total_matching_an_id_is_caught():
    # Live Gemini 2026-10-04: "14 total sanding trucks" = 7 + 7; 14 existed only as a district id.
    outs = [T.run_tool(n, {}) for n in ("get_storm_alert", "plan_response")]
    answer = ("For the plan, this means staging the heaviest response of 14 total sanding trucks "
              "in District 2 and District 14 while maintaining 1,640 known shelter beds.")
    res = trust.run_checks(answer, ["get_storm_alert", "plan_response"], outs, "How should we prepare?",
                           T.entity_catalog(), profile=trust.DALLAS)
    nums = next(c for c in res if c.name == "numbers_match_tools")
    assert nums.passed is False and "14 trucks" in nums.detail.replace("total sanding ", "")


@pytest.mark.parametrize("text, value", [("fourteen trucks", 14.0), ("twenty-one people", 21.0),
                                         ("8.8k customers", 8800.0), ("1.2 million", 1200000.0), ("a dozen", 12.0)])
def test_numbers_written_as_words_are_read(text, value):
    assert value in trust._numbers_in_text(text)


def test_dallas_planted_errors_all_caught_no_false_alarms():
    from evals.dallas_planted_errors import run
    res = run()
    should = [r for r in res["rows"] if r["expected"] != "expected_miss"]
    assert all(r["caught"] == r["planted"] > 0 for r in should), should
    assert res["false_alarms"] == 0


def test_past_storm_figure_equal_to_a_median_is_history_not_the_estimate():
    # Live Gemini 2026-10-04: ice_2023's 204 excess requests == estimate median 204.
    outs = [T.run_tool(n, {}) for n in ("get_storm_alert", "find_similar_storms", "estimate_demand")]
    calls = ["get_storm_alert", "find_similar_storms", "estimate_demand"]
    hist = "* February 2023 ice storm: peak 8,777 customers without power and 204 excess transport 311 requests."
    res = trust.run_checks(hist, calls, outs, "Has this happened before?", T.entity_catalog(), profile=trust.DALLAS)
    assert next(c for c in res if c.name == "confidence_fits_lead_time").passed is True
    est = "Plan for about 204 storm-driven street requests."
    res = trust.run_checks(est, calls, outs, "How bad?", T.entity_catalog(), profile=trust.DALLAS)
    assert next(c for c in res if c.name == "confidence_fits_lead_time").passed is False


def test_dallas_overview_endpoint_applies_what_if():
    from fastapi.testclient import TestClient
    import app as app_mod
    c = TestClient(app_mod.app)  # read-only route, no lifespan needed
    base = c.get("/api/overview").json()
    assert base["domain"] == "dallas" and base["diff"] is None
    assert set(base) == {"domain", "alert", "similar", "demand", "plan", "diff", "assets", "enso", "districts"}
    w = c.get("/api/overview", params={"max_trucks": 30, "closed": ["Fair Park"]}).json()
    assert w["plan"]["trucks_available"] == 30 and w["plan"]["shelter_shortfall_at_median"] == 760
    assert sum(ch["change"] for ch in w["diff"]["district_changes"]) == -20
    assert c.get("/api/overview", params={"closed": ["Nope"]}).status_code == 422
