"""Agent tools: the JSON schemas the LLM sees and the functions that run them.

Every tool currently returns stub data (see stub_data.py). To plug in a real
engine, replace the function body and keep the output keys the same.
Every output carries a "source" so the UI can show where numbers came from.
"""

import copy

from . import stub_data as data
from .contracts import CONTRACTS


def get_advisory() -> dict:
    return copy.deepcopy(data.ADVISORY)


def generate_scenarios() -> dict:
    return {"advisory_number": data.ADVISORY["advisory_number"], **copy.deepcopy(data.SCENARIOS)}


def get_enso_context() -> dict:
    return copy.deepcopy(data.ENSO)


def predict_impact(county_fips: list[str] | None = None) -> dict:
    rows = [c for c in data.COUNTIES if not county_fips or c["fips"] in county_fips]
    if county_fips and not rows:
        # LLMs guess FIPS codes; an empty list would read as "no impact" instead of "wrong code".
        return {"error": f"No impact prediction for FIPS {county_fips}. Known counties: "
                         + ", ".join(f"{c['name']} = {c['fips']}" for c in data.COUNTIES)}
    counties = []
    for c in rows:
        # Quantile order is enforced by contracts.Quantiles when run_tool validates.
        counties.append({k: copy.deepcopy(c[k]) for k in
                         ("fips", "name", "state", "risk_tier", "pct_customers_out", "customers_served", "why")})
    return {
        "advisory_number": data.ADVISORY["advisory_number"],
        "model_version": data.IMPACT_MODEL_VERSION,
        "counties": counties,
        "source": f"{data.STUB_SOURCE}; stands in for the XGBoost impact model",
    }


def solve_staging(max_trucks: int | None = None, unavailable_sites: list[str] | None = None) -> dict:
    """Highest-need-first truck allocation plus a shelter capacity check (stub)."""
    trucks = data.TRUCKS_AVAILABLE if max_trucks is None else max_trucks
    closed = {s.strip().lower() for s in unavailable_sites or []}

    remaining = trucks
    allocations = []
    for c in sorted(data.COUNTIES, key=lambda c: c["pct_customers_out"]["median"], reverse=True):
        assigned = min(c["truckloads_needed"], remaining)
        remaining -= assigned
        allocations.append({
            "county": c["name"],
            "fips": c["fips"],
            "truckloads_needed": c["truckloads_needed"],
            "truckloads_assigned": assigned,
            "truckloads_unmet": c["truckloads_needed"] - assigned,
        })

    open_shelters = [s for s in data.SHELTERS if s["id"].lower() not in closed]
    closed_shelters = [s["id"] for s in data.SHELTERS if s["id"].lower() in closed]
    # Pre-landfall plan, so evacuation (not post-impact) capacity is the bed count.
    beds = sum(s["evacuation_capacity"] for s in open_shelters)
    demand = sum(round(c["vulnerable_population"] * data.SHELTER_DEMAND_PCT_OF_VULNERABLE / 100)
                 for c in data.COUNTIES)

    return {
        "advisory_number": data.ADVISORY["advisory_number"],
        "method": "highest-need-first (stub; stochastic optimizer pending, Workstream B)",
        "staging_area": data.STAGING_AREA,
        "trucks_available": trucks,
        "allocations": allocations,
        "total_truckloads_unmet": sum(a["truckloads_unmet"] for a in allocations),
        "shelters_open": [s["id"] for s in open_shelters],
        "shelters_closed": closed_shelters,
        "shelter_beds_available": beds,
        "shelter_demand_estimate": demand,
        "shelter_bed_shortfall": max(0, demand - beds),
        "shelter_demand_assumption": (
            f"ASSUMPTION: {data.SHELTER_DEMAND_PCT_OF_VULNERABLE}% of the vulnerable population "
            "goes to public shelters (Bhattarai & Song); not validated"
        ),
        "source": data.STUB_SOURCE,
    }


def diff_plans(max_trucks: int | None = None, unavailable_sites: list[str] | None = None) -> dict:
    """What changes versus the unconstrained plan when the what-if constraints apply."""
    before = solve_staging()
    after = solve_staging(max_trucks, unavailable_sites)
    after_by_fips = {a["fips"]: a for a in after["allocations"]}
    changes = []
    for b in before["allocations"]:
        a = after_by_fips[b["fips"]]
        if a["truckloads_assigned"] != b["truckloads_assigned"]:
            changes.append({"county": b["county"], "fips": b["fips"],
                            "truckloads_before": b["truckloads_assigned"],
                            "truckloads_after": a["truckloads_assigned"],
                            "change": a["truckloads_assigned"] - b["truckloads_assigned"]})
    return {
        "advisory_number": after["advisory_number"],
        "baseline": {"trucks_available": before["trucks_available"], "shelters_closed": before["shelters_closed"]},
        "what_if": {"trucks_available": after["trucks_available"], "shelters_closed": after["shelters_closed"]},
        "county_changes": changes,
        "unmet_truckloads_before": before["total_truckloads_unmet"],
        "unmet_truckloads_after": after["total_truckloads_unmet"],
        "shelter_beds_before": before["shelter_beds_available"],
        "shelter_beds_after": after["shelter_beds_available"],
        "shelter_bed_shortfall_before": before["shelter_bed_shortfall"],
        "shelter_bed_shortfall_after": after["shelter_bed_shortfall"],
        "source": after["source"],
    }


def find_analogs() -> dict:
    return {
        "advisory_number": data.ADVISORY["advisory_number"],
        "analogs": copy.deepcopy(data.ANALOGS),
        "source": f"{data.STUB_SOURCE}; stands in for the HURDAT2 + ONI analog finder",
    }


def query_assets(county_fips: str | None = None) -> dict:
    shelters = [s for s in data.SHELTERS if not county_fips or s["county_fips"] == county_fips]
    if county_fips and county_fips not in {c["fips"] for c in data.COUNTIES}:
        # Same guard as predict_impact: [] for a guessed FIPS read as "Levy has no shelters".
        return {"error": f"Unknown county FIPS {county_fips}. Known counties: "
                         + ", ".join(f"{c['name']} = {c['fips']}" for c in data.COUNTIES)}
    return {"shelters": copy.deepcopy(shelters), "staging_area": data.STAGING_AREA,
            "source": data.STUB_SOURCE}


def retrieve_guidance(topic: str) -> dict:
    words = set(topic.lower().replace("?", " ").split())
    scored = sorted(data.GUIDANCE, key=lambda g: -len(words & set(g["keywords"])))
    return {"snippets": [g["text"] for g in scored[:2]], "source": data.GUIDANCE_SOURCE}


def _schema(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


TOOLS = {
    "get_advisory": (get_advisory, _schema(
        "get_advisory",
        "Get the current NHC advisory: storm name, advisory number, category, wind, "
        "lead time and forecast landfall. Call this first in every turn.")),
    "generate_scenarios": (generate_scenarios, _schema(
        "generate_scenarios",
        "Get the spread of possible storm tracks around the official forecast.")),
    "get_enso_context": (get_enso_context, _schema(
        "get_enso_context",
        "Get the current El Niño / La Niña state (NOAA Oceanic Niño Index) for seasonal context.")),
    "predict_impact": (predict_impact, _schema(
        "predict_impact",
        "Predict peak percent of customers without power per county (low/median/high), "
        "with risk tier and the main reasons (why).",
        {"county_fips": {"type": "array", "items": {"type": "string"},
                         "description": "Optional 5-digit FIPS codes to filter; omit for all counties."}})),
    "solve_staging": (solve_staging, _schema(
        "solve_staging",
        "Build the resource staging plan: truckloads per county and shelter capacity. "
        "Turn what-if statements into arguments and call again to re-plan.",
        {"max_trucks": {"type": "integer", "description": "Trucks available, if the user limits them."},
         "unavailable_sites": {"type": "array", "items": {"type": "string"},
                               "description": "Closed sites by id, e.g. [\"Shelter 4\"]."}})),
    "diff_plans": (diff_plans, _schema(
        "diff_plans",
        "Compare the plan under what-if constraints with the unconstrained plan: which counties "
        "gain or lose truckloads, and how unmet need and shelter beds change. Use the same "
        "arguments you gave solve_staging.",
        {"max_trucks": {"type": "integer", "description": "Trucks available, if the user limits them."},
         "unavailable_sites": {"type": "array", "items": {"type": "string"},
                               "description": "Closed sites by id, e.g. [\"Shelter 4\"]."}})),
    "find_analogs": (find_analogs, _schema(
        "find_analogs",
        "Find past storms most similar to this one (track, strength, El Niño phase) and their outages.")),
    "query_assets": (query_assets, _schema(
        "query_assets",
        "List shelters and staging areas, optionally for one county.",
        {"county_fips": {"type": "string", "description": "Optional 5-digit FIPS code."}})),
    "retrieve_guidance": (retrieve_guidance, _schema(
        "retrieve_guidance",
        "Search official FEMA / Ready.gov preparedness guidance for residents.",
        {"topic": {"type": "string", "description": "What the guidance should cover."}},
        ["topic"])),
}

TOOL_SCHEMAS = [schema for _, schema in TOOLS.values()]


def run_tool(name: str, arguments: dict) -> dict:
    if name not in TOOLS:
        return {"error": f"Unknown tool: {name}"}
    fn, schema = TOOLS[name]
    allowed = schema["function"]["parameters"]["properties"]
    unknown = set(arguments) - set(allowed)
    if unknown:
        return {"error": f"Unknown arguments for {name}: {sorted(unknown)}"}
    result = fn(**arguments)
    if "error" in result:  # tool-level error for the model to correct, not an engine output
        return result
    # Engine bug, not a model mistake: raise so it surfaces, don't hand the LLM a bad shape.
    CONTRACTS[name].model_validate(result)
    return result
