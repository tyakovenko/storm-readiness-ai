"""Storm Readiness AI tools for Google ADK.

Wraps the validated domain tools (advisories, impact forecasts, staging solver,
shelters, analog storms, guidance) with rich typing and docstrings for Gemini
function calling.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend package is in python path
_repo_root = Path(__file__).resolve().parent.parent
_backend_path = str(_repo_root / "backend")
if _backend_path not in sys.path:
    sys.path.insert(0, _backend_path)

from agent.tools import run_tool


def get_advisory() -> dict:
    """Get the current NHC advisory: storm name, advisory number, category, wind speed, lead time, and forecast landfall.

    Emergency managers call this first to establish active storm conditions.
    """
    return run_tool("get_advisory", {})


def generate_scenarios() -> dict:
    """Get the spread of possible storm tracks around the official NHC forecast track."""
    return run_tool("generate_scenarios", {})


def get_enso_context() -> dict:
    """Get the current El Niño / La Niña (ENSO) state via the NOAA Oceanic Niño Index for seasonal context."""
    return run_tool("get_enso_context", {})


def predict_impact(county_fips: list[str] | None = None) -> dict:
    """Predict peak percent of customers without power per county (low/median/high), risk tier, and key drivers (why).

    Args:
        county_fips: Optional list of 5-digit county FIPS codes to filter; omit for all counties.
    """
    args = {}
    if county_fips is not None:
        args["county_fips"] = county_fips
    return run_tool("predict_impact", args)


def solve_staging(max_trucks: int | None = None, unavailable_sites: list[str] | None = None) -> dict:
    """Build the resource staging plan: truckloads per county and shelter capacity.

    Turn what-if scenarios into arguments to re-plan.

    Args:
        max_trucks: Number of staging trucks available, if the user specifies a constraint.
        unavailable_sites: Closed sites or shelters by ID, e.g. ["Shelter 4"].
    """
    args = {}
    if max_trucks is not None:
        args["max_trucks"] = max_trucks
    if unavailable_sites is not None:
        args["unavailable_sites"] = unavailable_sites
    return run_tool("solve_staging", args)


def diff_plans(max_trucks: int | None = None, unavailable_sites: list[str] | None = None) -> dict:
    """Compare the plan under what-if constraints with the unconstrained baseline plan.

    Reports which counties gain or lose truckloads, and changes in unmet need and shelter beds.

    Args:
        max_trucks: Number of staging trucks available under the what-if constraint.
        unavailable_sites: Closed sites or shelters by ID under the what-if constraint.
    """
    args = {}
    if max_trucks is not None:
        args["max_trucks"] = max_trucks
    if unavailable_sites is not None:
        args["unavailable_sites"] = unavailable_sites
    return run_tool("diff_plans", args)


def find_analogs() -> dict:
    """Find past historical storms most similar to this one (track, strength, ENSO phase) and their outage impacts."""
    return run_tool("find_analogs", {})


def query_assets(county_fips: str | None = None) -> dict:
    """List shelters and staging areas, optionally filtered to a single county.

    Args:
        county_fips: Optional 5-digit county FIPS code (e.g. "12075").
    """
    args = {}
    if county_fips is not None:
        args["county_fips"] = county_fips
    return run_tool("query_assets", args)


def retrieve_guidance(topic: str) -> dict:
    """Search official FEMA / Ready.gov preparedness guidance for residents.

    Args:
        topic: The topic the guidance should cover (e.g. "evacuation kit", "food and water").
    """
    return run_tool("retrieve_guidance", {"topic": topic})


ALL_TOOLS = [
    get_advisory,
    generate_scenarios,
    get_enso_context,
    predict_impact,
    solve_staging,
    diff_plans,
    find_analogs,
    query_assets,
    retrieve_guidance,
]
