"""Dallas tools + the Dallas trust profile, no LLM.

Tools run on the processed tables (built from raw/dallas; skips if missing).
Trust tests plant one mistake each into an otherwise correct answer and check
the matching check catches it - and that the correct answer passes.
"""

import os

import pytest

os.environ["DALLAS_LIVE_ALERTS"] = "off"  # deterministic: always the labeled scenario

from agent import dallas_tools as T  # noqa: E402
from agent import trust  # noqa: E402
from dallas import build  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (build.RAW / "dallas311").exists(),
    reason="raw Dallas data missing: python data/sync_cloud_data.py pull --dataset dallas",
)


@pytest.fixture(scope="module", autouse=True)
def tables():
    build.build()
    from dallas import store
    store.table.cache_clear()


def run(name, **args):
    out = T.run_tool(name, args)
    assert "error" not in out, out
    return out


def test_every_tool_matches_its_contract():
    for name, args in [("get_storm_alert", {}), ("find_similar_storms", {}),
                       ("get_storm_impacts", {"storm_id": "fern_2026"}), ("estimate_demand", {}),
                       ("query_assets", {}), ("plan_response", {}), ("diff_plans", {"trucks": 30}),
                       ("get_enso_context", {}), ("retrieve_guidance", {"topic": "power outage"})]:
        run(name, **args)  # run_tool raises on a contract mismatch


def test_alert_is_labeled_scenario_and_live_check_is_visible():
    a = run("get_storm_alert")
    assert a["kind"] == "scenario" and a["headline"].startswith("SCENARIO")
    assert "disabled" in a["live_check"]


def test_similar_storms_ranked_and_caveat_names_el_nino():
    s = run("find_similar_storms")
    sims = [x["similarity"] for x in s["storms"]]
    assert sims == sorted(sims, reverse=True) and len(sims) == 4
    assert "El Niño" in s["caveat"]
    # Amounts can be overridden: an Uri-like storm puts Uri first.
    uri_like = run("find_similar_storms", min_temp_f=0, hours_below_freezing=140, snowfall_in=5, ice_accretion_in=0.03)
    assert uri_like["storms"][0]["storm_id"] == "uri_2021"


def test_demand_ranges_rest_on_documented_figures():
    d = run("estimate_demand")
    assert len(d["basis_storms"]) == 3
    assert d["shelter_guests_per_day"] == {"low": 950.0, "median": 1200.0, "high": 1314.0, "n": 3, "unit": "people"}
    assert len(d["by_district"]) == 14


def test_plan_allocates_every_truck_and_closures_cut_beds():
    p = run("plan_response")
    assert sum(a["trucks"] for a in p["truck_allocation"]) == 50
    assert p["shelter_beds_known"] == 1200 + 360 + 80
    assert p["shelters_unknown_capacity"] == ["fair_park_tower"]
    w = run("plan_response", trucks=30, unavailable_shelters=["Fair Park"])
    assert sum(a["trucks"] for a in w["truck_allocation"]) == 30
    assert w["shelter_beds_known"] == 360 + 80
    assert w["shelter_shortfall_at_median"] == 1200 - 440
    d = run("diff_plans", trucks=30, unavailable_shelters=["Fair Park"])
    assert sum(c["change"] for c in d["district_changes"]) == -20


def test_model_correctable_errors_name_the_valid_options():
    assert "uri_2021" in T.run_tool("get_storm_impacts", {"storm_id": "uri"})["error"]
    assert "oak_lawn_umc" in T.run_tool("plan_response", {"unavailable_shelters": ["Shelter 9"]})["error"]
    assert "Unknown arguments" in T.run_tool("plan_response", {"max_trucks": 3})["error"]


# ---- trust layer, Dallas profile ----

CALLS = ["get_storm_alert", "estimate_demand", "plan_response"]
GOOD = ("For this scenario, shelter demand is likely 950 to 1,314 people per day (median 1,200, from 3 past storms). "
        "With 50 trucks, District 2 gets 7 trucks and District 14 gets 7 trucks. "
        "Known shelter beds total 1,640, so the shortfall at the median is 0.")


@pytest.fixture(scope="module")
def outputs():
    return [run(c) for c in CALLS]


def checks(answer, outputs, calls=CALLS, question="How should we prepare for this storm?"):
    res = trust.run_checks(answer, calls, outputs, question, T.entity_catalog(), profile=trust.DALLAS)
    return {c.name: c for c in res}


def test_correct_answer_passes(outputs):
    res = checks(GOOD, outputs)
    assert all(c.passed for c in res.values()), {k: c.detail for k, c in res.items() if not c.passed}


BARE_MEDIAN = ("Expect about 1,200 people per day at shelters. "
               "With 50 trucks, District 2 gets 7 trucks and District 14 gets 7 trucks.")


@pytest.mark.parametrize("answer, broken", [
    (GOOD + " Winter Storm Uri left 400,000 customers without power.", "numbers_match_tools"),
    (GOOD + " District 2 gets 4 trucks.", "numbers_match_tools"),        # 4 is District 13's / 1's
    (GOOD + " District 15 gets 7 trucks.", "entities_match_tools"),      # no District 15
    (BARE_MEDIAN, "confidence_fits_lead_time"),                          # median without its range
    (GOOD + " Fair Park will definitely fill up.", "confidence_fits_lead_time"),  # certainty at 36 h lead
])
def test_planted_error_is_caught(outputs, answer, broken):
    res = checks(answer, outputs)
    assert res[broken].passed is False, res[broken].detail


def test_number_only_in_a_citation_is_not_evidence(outputs):
    # plan_response's source cites "FOX 4"; 4 must not back "District 2 gets 4 trucks".
    assert "FOX 4" in outputs[2]["source"]
    res = checks("District 2 gets 4 trucks.", outputs)
    assert res["numbers_match_tools"].passed is False


def test_order_and_plan_tool_are_required(outputs):
    res = checks(GOOD, outputs, calls=["estimate_demand", "get_storm_alert", "plan_response"])
    assert res["required_steps"].passed is False and "before" not in res["required_steps"].detail
    res = checks("Send 7 trucks to District 2.", outputs[:2], calls=CALLS[:2])
    assert res["required_steps"].passed is False and "plan_response" in res["required_steps"].detail


def test_user_number_with_other_unit_is_not_a_bare_median(outputs):
    res = checks(GOOD + " With only 30 trucks, District 2 drops.", outputs, question="What if we only have 30 trucks?")
    assert res["confidence_fits_lead_time"].passed and res["numbers_match_tools"].passed


def test_hurricane_profile_unchanged_by_default():
    assert trust.HURRICANE.first_tool == "get_advisory"
    assert trust.run_checks.__defaults__[-1] is trust.HURRICANE
