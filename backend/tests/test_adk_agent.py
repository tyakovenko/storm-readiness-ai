"""Tests for Google ADK storm_agent integration."""

import pytest
from google.adk.tools import FunctionTool
from storm_agent.agent import root_agent
from storm_agent.tools import (
    ALL_TOOLS,
    get_advisory,
    generate_scenarios,
    get_enso_context,
    predict_impact,
    solve_staging,
    diff_plans,
    find_analogs,
    query_assets,
    retrieve_guidance,
)
from agent.contracts import CONTRACTS


def test_adk_agent_configuration():
    assert root_agent.name == "root_agent"
    assert "Storm Readiness" in root_agent.instruction
    assert len(root_agent.tools) == 9
    expected_tool_names = {
        "get_advisory",
        "generate_scenarios",
        "get_enso_context",
        "predict_impact",
        "solve_staging",
        "diff_plans",
        "find_analogs",
        "query_assets",
        "retrieve_guidance",
    }
    actual_tool_names = {t.__name__ for t in root_agent.tools}
    assert actual_tool_names == expected_tool_names


def test_all_tools_generate_valid_adk_declarations():
    for tool in ALL_TOOLS:
        ft = FunctionTool(tool)
        decl = ft._get_declaration()
        assert decl.name == tool.__name__
        assert decl.description is not None
        assert len(decl.description) > 10


def test_adk_tools_return_valid_contracts():
    adv = get_advisory()
    CONTRACTS["get_advisory"].model_validate(adv)

    scenarios = generate_scenarios()
    CONTRACTS["generate_scenarios"].model_validate(scenarios)

    enso = get_enso_context()
    CONTRACTS["get_enso_context"].model_validate(enso)

    impact = predict_impact()
    CONTRACTS["predict_impact"].model_validate(impact)

    staging = solve_staging(max_trucks=6, unavailable_sites=["Shelter 2"])
    CONTRACTS["solve_staging"].model_validate(staging)
    assert staging["trucks_available"] == 6
    assert "Shelter 2" in staging["shelters_closed"]

    diff = diff_plans(max_trucks=6, unavailable_sites=["Shelter 2"])
    CONTRACTS["diff_plans"].model_validate(diff)
    assert diff["what_if"]["trucks_available"] == 6

    analogs = find_analogs()
    CONTRACTS["find_analogs"].model_validate(analogs)

    assets = query_assets()
    CONTRACTS["query_assets"].model_validate(assets)

    guidance = retrieve_guidance("evacuation kit")
    CONTRACTS["retrieve_guidance"].model_validate(guidance)
    assert len(guidance["snippets"]) > 0
