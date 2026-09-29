"""Mock-mode tests: no key, no network. Run from backend/: .venv/bin/pytest -q"""

import pytest
from pydantic import ValidationError

from agent import tools, trust
from agent.contracts import CONTRACTS
from agent.loop import run_agent
from agent.mock_llm import MockLLM

EXAMPLES = [
    "What's the outage risk by county?",
    "Where should we stage trucks?",
    "We only have 6 trucks and Shelter 2 is closed. Re-plan.",
    "Were there similar storms before?",
    "What should residents do now?",
    "How does El Niño affect this season?",
]


@pytest.mark.parametrize("question", EXAMPLES)
def test_examples_pass_first_try(question):
    r = run_agent(question, [], MockLLM())
    assert r["status"] == "passed", r["checks"]


@pytest.mark.parametrize("question,check", [
    ("Trust demo: hallucinate a number", "numbers_match_tools"),
    ("Trust demo: overconfident outage risk", "confidence_fits_lead_time"),
])
def test_trust_demos_block_then_regenerate(question, check):
    r = run_agent(question, [], MockLLM())
    assert r["status"] == "regenerated"
    first = {c["name"]: c["passed"] for c in r["attempts"][0]["checks"]}
    assert first[check] is False


def test_judge_reported_not_configured_not_silently_passed():
    r = run_agent(EXAMPLES[0], [], MockLLM())
    judge = next(c for c in r["checks"] if c["name"] == "actionable")
    assert judge["passed"] is None and "JUDGE_MODEL" in judge["detail"]


@pytest.mark.parametrize("name", sorted(tools.TOOLS))
def test_stub_outputs_meet_contract(name):
    args = {"topic": "water"} if name == "retrieve_guidance" else {}
    CONTRACTS[name].model_validate(tools.run_tool(name, args))


def test_every_tool_has_a_contract():
    assert set(tools.TOOLS) == set(CONTRACTS)


def test_contract_rejects_crossed_quantiles_and_int_fips():
    bad = tools.predict_impact()
    bad["counties"][0]["pct_customers_out"] = {"low": 60, "median": 50, "high": 70}
    with pytest.raises(ValidationError):
        CONTRACTS["predict_impact"].model_validate(bad)
    bad = tools.predict_impact()
    bad["counties"][0]["fips"] = "1075"  # EAGLE-I int FIPS that lost its leading zero
    with pytest.raises(ValidationError):
        CONTRACTS["predict_impact"].model_validate(bad)


def test_diff_plans_matches_two_solves():
    d = tools.diff_plans(max_trucks=6, unavailable_sites=["Shelter 2"])
    after = tools.solve_staging(6, ["Shelter 2"])
    assert d["unmet_truckloads_after"] == after["total_truckloads_unmet"]
    assert d["shelter_beds_after"] == after["shelter_beds_available"]
    assert all(c["change"] == c["truckloads_after"] - c["truckloads_before"] for c in d["county_changes"])


def test_negative_change_in_answer_is_not_flagged():
    outputs = [{"change": -2}]
    assert trust.check_numbers("Dixie drops by 2 truckloads", outputs, "").passed


def test_stale_advisory_blocked():
    outputs = [tools.get_advisory(), {**tools.predict_impact(), "advisory_number": 13}]
    c = trust.check_steps("ok", ["get_advisory", "predict_impact"], outputs)
    assert c.passed is False and "13" in c.detail


def test_short_lead_time_allows_point_estimates():
    adv = {**tools.get_advisory(), "lead_time_to_landfall_h": 24}
    c = trust.check_confidence("Levy County: 55% out", [adv, tools.predict_impact()])
    assert c.passed is True


def test_unknown_fips_returns_error_not_empty():
    r = tools.run_tool("predict_impact", {"county_fips": ["12083"]})
    assert "error" in r and "12075" in r["error"]
