"""Agent tools: the JSON schemas the LLM sees and the functions that run them.

Every tool currently returns stub data (see stub_data.py). To plug in a real
engine, replace the function body and keep the output keys the same.
Every output carries a "source" so the UI can show where numbers came from.
"""

import copy

from . import stub_data as data


def get_advisory() -> dict:
    return copy.deepcopy(data.ADVISORY)


def generate_scenarios() -> dict:
    return {"advisory_number": data.ADVISORY["advisory_number"], **copy.deepcopy(data.SCENARIOS)}


def predict_impact(county_fips: list[str] | None = None) -> dict:
    rows = [c for c in data.COUNTIES if not county_fips or c["fips"] in county_fips]
    counties = []
    for c in rows:
        q = c["pct_customers_out"]
        # CLAUDE.md rule 4: enforce quantile order, don't assume it.
        if not q["low"] <= q["median"] <= q["high"]:
            raise ValueError(f"Quantiles out of order for {c['fips']}: {q}")
        counties.append({k: copy.deepcopy(c[k]) for k in
                         ("fips", "name", "risk_tier", "pct_customers_out", "customers_served", "why")})
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
    beds = sum(s["beds"] for s in open_shelters)
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


def find_analogs() -> dict:
    return {
        "advisory_number": data.ADVISORY["advisory_number"],
        "analogs": copy.deepcopy(data.ANALOGS),
        "source": f"{data.STUB_SOURCE}; stands in for the HURDAT2 + ONI analog finder",
    }


def query_assets(county_fips: str | None = None) -> dict:
    shelters = [s for s in data.SHELTERS if not county_fips or s["county_fips"] == county_fips]
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
    return fn(**arguments)
