"""Hurricane county agents (template x pack) in mock mode.

Needs the published packs (local data/processed/packs/hurricane or GCS) and, for estimate_impact,
HURRICANE_MODEL_RUN pointing at a trained model in GCS. Skips with the reason otherwise.
"""

import os

import pytest

from agent import trust

try:
    from hurricane import store
    INDEX = store.index()
except Exception as e:  # no packs published
    INDEX, WHY = [], str(e)
else:
    WHY = ""

pytestmark = pytest.mark.skipif(not INDEX, reason=f"hurricane packs unavailable: {WHY[:120]}")
FIPS = [p["fips"] for p in INDEX]


@pytest.fixture(scope="module", params=FIPS)
def county(request):
    from agent.hurricane_adk import build_county_agent
    agent, ts = build_county_agent(request.param, "mock")
    return request.param, agent, ts


def test_every_tool_matches_its_contract(county):
    _, _, ts = county
    for name, args in [("get_storm_alert", {}), ("find_similar_storms", {}), ("query_assets", {}),
                       ("plan_shelters", {}), ("diff_plans", {"exclude_surge_and_floodplain": False}),
                       ("get_enso_context", {}), ("retrieve_guidance", {"topic": "evacuation"})]:
        out = ts.run_tool(name, args)
        assert "error" not in out, (name, out)
    storm = ts._storms()[0]["storm_id"]
    assert "error" not in ts.run_tool("get_storm_impacts", {"storm_id": storm})


def test_alert_is_a_labeled_replay(county):
    _, _, ts = county
    a = ts.run_tool("get_storm_alert", {})
    assert a["kind"] == "replay" and a["headline"].startswith("REPLAY") and 30 <= a["lead_time_h"] <= 72


def test_estimate_impact_or_visible_error(county):
    """Phase 4: the default engine is the local model bundle (models/model_bundle.py), which
    needs no HURRICANE_MODEL_RUN/GCS -- so this now succeeds by default. If the bundle artifact
    itself is missing, it must still be a visible error, never a silent stub."""
    _, _, ts = county
    out = ts.run_tool("estimate_impact", {})
    if "error" in out:
        assert "not available" in out["error"]
    else:
        r = out["pct_customers_out"]
        assert r["low"] <= r["median"] <= r["high"] and r["unit"] == "%"
        assert out["engine"] == "bundle"
        assert out["model_version"]


def test_legacy_engine_without_model_run_is_a_visible_error(county, monkeypatch):
    """The original HURRICANE_MODEL_RUN+GCS engine is untouched and still reachable -- its
    original guarantee (no silent stub without HURRICANE_MODEL_RUN) still holds."""
    import agent.hurricane_tools as ht
    monkeypatch.setattr(ht, "IMPACT_ENGINE", "legacy_gcs")
    _, _, ts = county
    out = ts.run_tool("estimate_impact", {})
    if not os.getenv("HURRICANE_MODEL_RUN"):
        assert "error" in out and "HURRICANE_MODEL_RUN" in out["error"]
    else:
        r = out["pct_customers_out"]
        assert r["low"] <= r["median"] <= r["high"]


def test_ask_ai_compose_does_not_crash_when_impact_is_unavailable():
    """Phase 4 fix: hurricane_adk._compose must never crash on estimate_impact's error dict
    (the pre-existing bug Phase 2 found)."""
    from agent.hurricane_adk import _compose
    text = _compose({"estimate_impact": {"error": "Impact model not available: test."}})
    assert "Outage model unavailable" in text
    assert "test." in text


def test_ask_ai_compose_does_not_crash_with_no_forecast_in_outputs():
    """Phase 5 Part L #8: a missing/empty tool-output set (no get_storm_alert at all) must still
    produce the generic fallback line, never a KeyError/crash."""
    from agent.hurricane_adk import _compose
    assert _compose({}) == "I couldn't find data for that. Ask about outages, shelters or past storms."
    assert "Outage model unavailable" in _compose({"estimate_impact": {"error": "x"}}, "Which county is highest risk?")


@pytest.mark.parametrize("question,expect_substrings", [
    # EXPLAINABILITY (Part C): the drivers come from estimate_impact's own "why", phrased as
    # inputs, never as a claimed cause or a ranked importance the model doesn't actually report.
    ("Why is this county high risk?", ["generated using factors including", "not a ranked feature-importance"]),
    # UNCERTAINTY (Part D): the calibrated range and its status, not a bare point estimate.
    ("How reliable is this prediction?", ["calibrated uncertainty interval", "Calibration status:"]),
    # SOURCES (Part E): only the real provenance strings, never an invented dataset or URL.
    ("Where did this prediction come from?", ["Outage estimate:", "Forecast:"]),
])
def test_mock_answers_cover_the_new_phase5_intents(county, question, expect_substrings):
    from agent.hurricane_adk import run_county_agent
    _, agent, ts = county
    r = run_county_agent(question, [], agent, ts)
    assert r["status"] == "passed", r["attempts"]
    if r["answer"] and "Outage model unavailable" not in r["answer"]:
        for s in expect_substrings:
            assert s in r["answer"], r["answer"]


def test_cross_county_ranking_is_refused_not_fabricated(county):
    """Phase 5 Part J: this agent has a trained prediction for exactly one county. Asked to rank
    or compare across counties, it must say it can't -- never invent a multi-county comparison."""
    from agent.hurricane_adk import run_county_agent
    _, agent, ts = county
    r = run_county_agent("Which county is the highest risk right now?", [], agent, ts)
    assert r["status"] == "passed", r["attempts"]
    if r["answer"] and "Outage model unavailable" not in r["answer"]:
        assert "can't rank or compare risk across counties" in r["answer"]


def test_replay_is_never_described_as_live(county):
    from agent.hurricane_adk import run_county_agent
    _, agent, ts = county
    r = run_county_agent("What is expected from this storm?", [], agent, ts)
    assert r["status"] == "passed", r["attempts"]
    assert "not a live storm" in r["answer"]
    assert "This is a live" not in r["answer"]


def test_shelter_exposure_question_uses_real_shelter_data(county):
    """Phase 5 Part L #5/#B: "which facilities need attention" routes to real shelter exposure
    data (query_assets), not a generic shelter-plan reply."""
    from agent.hurricane_adk import run_county_agent
    _, agent, ts = county
    r = run_county_agent("Which exposed facilities need attention?", [], agent, ts)
    assert r["status"] == "passed", r["attempts"]
    assert any(c["name"] == "estimate_impact" for c in r["tool_calls"])
    assert any(c["name"] == "query_assets" for c in r["tool_calls"])


def test_wrong_ids_name_valid_options(county):
    _, _, ts = county
    assert "Known" in ts.run_tool("get_storm_impacts", {"storm_id": "AL999999"})["error"]
    assert "Unknown shelter" in ts.run_tool("plan_shelters", {"unavailable_shelters": ["Shelter 9999"]})["error"]


@pytest.mark.parametrize("question", ["Has this county had a storm like this before?",
                                      "What shelters do we have?", "What should residents do to evacuate?",
                                      "Does El Niño matter this season?"])
def test_mock_answers_pass_trust(county, question):
    from agent.hurricane_adk import run_county_agent
    _, agent, ts = county
    r = run_county_agent(question, [], agent, ts)
    assert r["status"] == "passed", r["attempts"]


def test_bare_median_blocked_then_regenerated(county):
    if not os.getenv("HURRICANE_MODEL_RUN"):
        pytest.skip("needs the trained model")
    from agent.hurricane_adk import build_county_agent, run_county_agent
    fips, _, _ = county
    agent, ts = build_county_agent(fips, "mock", bad_first=True)
    r = run_county_agent("How bad will the outages be?", [], agent, ts)
    assert r["status"] == "regenerated"
    first = {c["name"]: c["passed"] for c in r["attempts"][0]["checks"]}
    assert first["confidence_fits_lead_time"] is False


def test_storm_name_lee_does_not_collide_with_lee_county():
    cat_names = {n for p in INDEX for n in []}  # placeholder to keep module import-light
    from agent.hurricane_tools import HurricaneToolset
    if "12071" not in FIPS:
        pytest.skip("Lee County pack not built")
    names = {n for e in HurricaneToolset("12071").entity_catalog() if e["kind"] == "storm" for n in e["names"]}
    assert "Lee" not in names and "Lee County" not in names
    assert trust.HURRICANE_COUNTY.uncertain_lead_h == 48
