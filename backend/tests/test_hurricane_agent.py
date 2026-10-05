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
                       ("get_enso_context", {}), ("retrieve_guidance", {"topic": "evacuation"}),
                       ("get_local_facts", {})]:
        out = ts.run_tool(name, args)
        assert "error" not in out, (name, out)
    storm = ts._storms()[0]["storm_id"]
    assert "error" not in ts.run_tool("get_storm_impacts", {"storm_id": storm})


def test_alert_is_a_labeled_replay(county):
    _, _, ts = county
    a = ts.run_tool("get_storm_alert", {})
    assert a["kind"] == "replay" and a["headline"].startswith("REPLAY") and 30 <= a["lead_time_h"] <= 72


def test_estimate_impact_or_visible_error(county):
    _, _, ts = county
    out = ts.run_tool("estimate_impact", {})
    if not os.getenv("HURRICANE_MODEL_RUN"):
        assert "error" in out and "HURRICANE_MODEL_RUN" in out["error"]   # never a silent stub
    else:
        r = out["pct_customers_out"]
        assert r["low"] <= r["median"] <= r["high"] and r["unit"] == "%"


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


PUBLISHED = {"metric": "shelter_capacity", "value": 2000, "value_raw": "2,000", "unit": "people", "qualifier": "over",
             "storm_id": None, "place": "Houston", "subject": "City of Houston", "as_of": "2024",
             "quote": "City shelters could hold more than 2,000 people; Fair Park opened in 1998.",
             "source": "AAR", "source_url": "https://x.gov/aar", "publisher": "City of Houston",
             "verdict": "single_source", "corroborating_urls": []}


def test_local_facts_empty_until_published():
    from agent.hurricane_tools import HurricaneToolset
    out = HurricaneToolset(FIPS[0]).run_tool("get_local_facts", {})
    assert out["facts"] == [] and "No researched local facts" in out["note"]


def test_local_facts_published_filtered_and_cited():
    from agent.hurricane_tools import HurricaneToolset
    ts = HurricaneToolset(FIPS[0])
    storm = ts._storms()[0]
    ts.pack = {**ts.pack, "facts": [PUBLISHED, {**PUBLISHED, "metric": "evacuee_count", "value": 1314, "qualifier": "exact",
                                                "storm_id": storm["storm_id"]}],
               "research": {"reviewer": "Taya", "approved_utc": "2026-10-05T00:00:00+00:00", "gaps_reported": []}}
    out = ts.run_tool("get_local_facts", {"metric": "evacuee_count"})
    assert [f["value"] for f in out["facts"]] == [1314] and out["facts"][0]["storm"] == storm["name"]
    assert out["reviewed_by"] == "Taya" and out["metrics_available"] == ["evacuee_count", "shelter_capacity"]
    assert "error" in ts.run_tool("get_local_facts", {"storm_id": "AL999999"})
    # numbers inside the quote (1998) are citation, not evidence the answer may use
    nums = trust._numbers_in_output(ts.run_tool("get_local_facts", {}))
    assert 2000 in nums and 1998 not in nums
