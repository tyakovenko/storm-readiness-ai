"""Dallas County tools: what the agent can look up and compute.

All numbers come from the processed Dallas tables (dallas/store.py), which
carry their sources. Nothing here forecasts: demand is a low/median/high range
over past Dallas storms, with n stated, because n is 2-4.

The storm itself is a labeled SCENARIO unless NWS has a live winter alert for
Dallas County (decision 2026-10-04: no winter storm is active in October).
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import time
import urllib.request
from statistics import median

from dallas import store

from .dallas_contracts import CONTRACTS

log = logging.getLogger(__name__)

COUNTY_NAME = "Dallas County"
NWS_ZONE = "TXZ119"  # Dallas County forecast zone
WINTER_EVENTS = {"Winter Storm Warning", "Winter Storm Watch", "Ice Storm Warning",
                 "Winter Weather Advisory", "Extreme Cold Warning", "Extreme Cold Watch",
                 "Cold Weather Advisory", "Blizzard Warning"}
DEFAULT_TRUCKS = 50  # Jan 2025 sanding fleet (sources.RESOURCES)

# Demo scenario. Every value sits inside the range of the four past Dallas winter
# storms (ice 0.01-0.36 in, min temp -0.9-26 F, 10-140 h below freezing, snow
# 1.3-5.0 in), so similarity and demand ranges stay within observed history.
SCENARIO = {
    "scenario_id": "scenario-ice-2026-27",
    "headline": "SCENARIO (not a real alert): ice storm warning for Dallas County",
    "onset_hours_from_now": 36,
    "hazards": {"ice_accretion_in": 0.25, "min_temp_f": 20.0, "hours_below_freezing": 60.0, "snowfall_in": 1.0},
    "note": ("Hypothetical storm for planning practice, modeled on a strong-El Niño winter "
             "(wet, with arctic air arriving). Values chosen within the range of Dallas "
             "storms 2021-2026."),
}
FEATURES = ["ice_accretion_in", "min_temp_f", "hours_below_freezing", "snowfall_in"]

_live_cache: dict = {"t": 0.0, "value": None}
LIVE_CACHE_S = 300


def _live_alert() -> tuple[dict | None, str]:
    """NWS active alerts for the Dallas zone. Returns (alert or None, what happened)."""
    if os.getenv("DALLAS_LIVE_ALERTS", "on").lower() in {"off", "0", "false"}:
        return None, "live check disabled (DALLAS_LIVE_ALERTS=off)"
    if time.time() - _live_cache["t"] < LIVE_CACHE_S:
        return _live_cache["value"]
    try:
        req = urllib.request.Request(f"https://api.weather.gov/alerts/active?zone={NWS_ZONE}",
                                     headers={"User-Agent": "storm-readiness-ai (demo)",
                                              "Accept": "application/geo+json"})
        with urllib.request.urlopen(req, timeout=4) as r:
            feats = json.load(r).get("features", [])
        winter = [f["properties"] for f in feats if f["properties"].get("event") in WINTER_EVENTS]
        result = (winter[0], f"live NWS alert active: {winter[0]['event']}") if winter \
            else (None, "no active NWS winter alert for Dallas County; using scenario")
    except Exception as e:  # visible in the tool output, not swallowed
        log.error("NWS live alert check failed: %s", e)
        result = (None, f"live NWS check FAILED ({type(e).__name__}); using scenario")
    _live_cache.update(t=time.time(), value=result)
    return result


def get_storm_alert() -> dict:
    live, live_check = _live_alert()
    if live:
        return {
            "scenario_id": f"live-{live.get('id', '')[-12:]}",
            "kind": "live",
            "headline": live.get("headline") or live["event"],
            "area": COUNTY_NAME,
            "onset_local": live.get("onset") or live.get("effective") or "",
            "lead_time_h": 0.0,
            "hazards": None,
            "live_check": live_check,
            "note": "Live alert text has no structured ice/temperature amounts; pass them to "
                    "find_similar_storms if the user gives them.",
            "source": "NWS api.weather.gov active alerts, zone TXZ119",
        }
    return {
        "scenario_id": SCENARIO["scenario_id"],
        "kind": "scenario",
        "headline": SCENARIO["headline"],
        "area": COUNTY_NAME,
        "onset_local": f"in {SCENARIO['onset_hours_from_now']} hours",
        "lead_time_h": float(SCENARIO["onset_hours_from_now"]),
        "hazards": dict(SCENARIO["hazards"]),
        "live_check": live_check,
        "note": SCENARIO["note"],
        "source": "Demo scenario (storm-readiness team), bounded by Dallas storm history",
    }


def _winter_storms() -> list[dict]:
    return [s for s in store.storms() if s["hazard"] == "winter" and s["weather"]]


def _ranked(hazards: dict) -> list[tuple[float, dict]]:
    storms = _winter_storms()
    spans = {f: (max(s["weather"][f] for s in storms) - min(s["weather"][f] for s in storms)) or 1.0
             for f in FEATURES}
    ranked = []
    for s in storms:
        d = math.sqrt(sum(((hazards[f] - s["weather"][f]) / spans[f]) ** 2 for f in FEATURES) / len(FEATURES))
        ranked.append((round(max(0.0, 1 - d), 3), s))
    return sorted(ranked, key=lambda x: -x[0])


def _hazards_or_error(ice_accretion_in, min_temp_f, hours_below_freezing, snowfall_in):
    alert = get_storm_alert()
    given = {"ice_accretion_in": ice_accretion_in, "min_temp_f": min_temp_f,
             "hours_below_freezing": hours_below_freezing, "snowfall_in": snowfall_in}
    base = alert["hazards"] or {}
    hazards = {f: (given[f] if given[f] is not None else base.get(f)) for f in FEATURES}
    missing = [f for f, v in hazards.items() if v is None]
    if missing:
        return alert, {"error": f"Missing storm amounts {missing}: the live alert has none. "
                                "Ask the user or pass them as arguments."}
    return alert, hazards


def find_similar_storms(ice_accretion_in: float | None = None, min_temp_f: float | None = None,
                        hours_below_freezing: float | None = None, snowfall_in: float | None = None) -> dict:
    alert, hazards = _hazards_or_error(ice_accretion_in, min_temp_f, hours_below_freezing, snowfall_in)
    if "error" in hazards:
        return hazards
    enso = store.climate()["enso_latest"]
    out = []
    for sim, s in _ranked(hazards):
        o = s["outages"] or {}
        out.append({"storm_id": s["id"], "name": s["name"], "event_dates": s["event_dates"],
                    "similarity": sim, "weather": {f: s["weather"][f] for f in FEATURES},
                    "peak_customers_out": o.get("peak_customers_out"),
                    "peak_pct_customers": o.get("peak_pct_customers"),
                    "excess_311_by_sector": s["impacts_311"]["excess_by_sector"],
                    "enso_phase": (s.get("enso") or {}).get("phase")})
    phases = {x["enso_phase"] for x in out}
    caveat = (f"Only {len(out)} past Dallas winter storms. Similarity compares weather at DFW only. "
              f"Current ENSO: {enso['phase']} ({enso['strength']}); past storms were {', '.join(sorted(p for p in phases if p))} "
              "- none under El Niño, so this winter is outside the comparison set.")
    return {"scenario_id": alert["scenario_id"], "compared_on": FEATURES, "storms": out, "caveat": caveat,
            "source": "Processed Dallas tables: IEM ASOS + GHCN-Daily (DFW), EAGLE-I, Dallas 311, NOAA CPC ONI"}


def get_storm_impacts(storm_id: str) -> dict:
    s = store.storm(storm_id)
    if s is None:
        return {"error": f"Unknown storm_id {storm_id!r}. Known: "
                         + ", ".join(f"{x['id']} ({x['name']})" for x in store.storms())}
    i = s["impacts_311"]
    # Districts with the most storm-day requests in impact sectors (not "other").
    per = {d: sum(v for k, v in sec.items() if k != "other") for d, sec in i["storm_requests_by_district"].items()}
    top = [{"district": d, "storm_day_requests": n} for d, n in sorted(per.items(), key=lambda x: -x[1])[:5]]
    narrative = s["noaa"]["episode_narratives"][0] if s["noaa"]["episode_narratives"] else None
    return {
        "storm_id": s["id"], "name": s["name"], "event_dates": s["event_dates"],
        "weather": s["weather"], "outages": s["outages"],
        "surges_311": i["surges"][:8], "excess_311_by_sector": i["excess_by_sector"],
        "top_districts": top,
        "noaa_events": [{k: e[k] for k in ("event_type", "begin", "deaths", "injuries", "damage_property")}
                        for e in s["noaa"]["events"]],
        "noaa_narrative": narrative,
        "fema": s["fema"],
        "city_response": s["city_response"],
        "sources": ["Dallas 311 (Dallas OpenData 4n3h-rfqm)", "NOAA Storm Events", "OpenFEMA",
                    "EAGLE-I (ORNL)", "IEM ASOS / GHCN-Daily (DFW)"]
                   + sorted({f["source"] for f in s["city_response"]}),
    }


def _range(values: list[float], unit: str) -> dict | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    return {"low": float(vals[0]), "median": float(median(vals)), "high": float(vals[-1]), "n": len(vals), "unit": unit}


def _shelter_figures() -> list[float]:
    """Every documented shelter headcount: actual daily averages, plans, and the historic peak."""
    figs = []
    for s in store.storms():
        for f in s["city_response"]:
            if f["metric"] in {"shelter_avg_daily_guests", "shelter_planned_guests"}:
                figs.append(f["value"])
    figs += [h["value"] for h in store.assets()["shelter_history"] if h["metric"] == "peak_guests"]
    return figs


def estimate_demand(top_k: int = 3) -> dict:
    alert = get_storm_alert()
    if not alert["hazards"]:
        return {"error": "No storm amounts on the live alert; call find_similar_storms with amounts first."}
    basis = [s for _, s in _ranked(alert["hazards"])[:top_k]]
    transport = _range([s["impacts_311"]["excess_by_sector"].get("transport", 0) for s in basis], "requests")
    outages = _range([(s["outages"] or {}).get("peak_customers_out") for s in basis], "customers")
    shares = {f["properties"]["district"]: f["properties"]["winter_transport_share"]
              for f in store.districts()["features"]}
    by_district = [{"district": d, "transport_requests": {
        "low": round(transport["low"] * w, 1), "median": round(transport["median"] * w, 1),
        "high": round(transport["high"] * w, 1), "n": transport["n"], "unit": "requests"}}
        for d, w in sorted(shares.items(), key=lambda x: -x[1])]
    return {
        "scenario_id": alert["scenario_id"],
        "basis_storms": [s["id"] for s in basis],
        "shelter_guests_per_day": _range(_shelter_figures(), "people"),
        "transport_requests_storm_days": transport,
        "peak_customers_out": outages,
        "by_district": by_district,
        "method": (f"Ranges = low/median/high over the {top_k} most similar past storms (311 storm-driven "
                   "transport requests, EAGLE-I peak outages). Shelter range = every documented Dallas "
                   "shelter headcount (Jan 2025 daily average, Jan 2026 plan, 2023-24 peak). District split = "
                   "each council district's share of past winter transport requests."),
        "caveat": "History-based range, not a forecast model; n is small and no past storm was under El Niño.",
        "source": "Processed Dallas tables (311, EAGLE-I, city memos/briefings, news)",
    }


def query_assets() -> dict:
    a = store.assets()
    return {"shelters": copy.deepcopy(a["inclement_weather_shelters"]), "resources": copy.deepcopy(a["resources"]),
            "departments": dict(a["departments"]), "department_staff": copy.deepcopy(a["department_staff"]),
            "shelter_history": copy.deepcopy(a["shelter_history"]),
            "evacuee_shelters_nss": copy.deepcopy(a["evacuee_shelters_nss"]),
            "source": "City of Dallas memos/briefings, Budget Book FY2025-26, news, FEMA NSS"}


def _sites() -> list[dict]:
    return store.assets()["inclement_weather_shelters"]


def _match_sites(names: list[str] | None) -> tuple[set[str], list[str]]:
    sites = _sites()
    closed, unknown = set(), []
    for n in names or []:
        key = n.strip().lower()
        hit = [s["id"] for s in sites if key in {s["id"].lower(), s["name"].lower()} or key in s["name"].lower()]
        if hit:
            closed.update(hit)
        else:
            unknown.append(n)
    return closed, unknown


def _allocate(trucks: int) -> list[dict]:
    """Largest-remainder split of trucks by each district's share of past winter transport requests."""
    feats = [f["properties"] for f in store.districts()["features"]]
    raw = [(p["district"], p["winter_transport_share"], trucks * p["winter_transport_share"]) for p in feats]
    base = {d: int(x) for d, _, x in raw}
    left = trucks - sum(base.values())
    for d, _, x in sorted(raw, key=lambda r: -(r[2] - int(r[2])))[:left]:
        base[d] += 1
    return [{"district": d, "trucks": base[d], "weight": w}
            for d, w, _ in sorted(raw, key=lambda r: (-r[1], int(r[0])))]


def plan_response(trucks: int | None = None, unavailable_shelters: list[str] | None = None) -> dict:
    alert = get_storm_alert()
    closed, unknown = _match_sites(unavailable_shelters)
    if unknown:
        return {"error": f"Unknown shelter(s) {unknown}. Known: "
                         + ", ".join(f"{s['id']} ({s['name']})" for s in _sites())}
    n = DEFAULT_TRUCKS if trucks is None else trucks
    open_sites = [s for s in _sites() if s["id"] not in closed]
    beds = sum(s["capacity"] for s in open_sites if s["capacity"] is not None)
    demand = _range(_shelter_figures(), "people")
    staff = {r["department"]: r for r in store.assets()["department_staff"]["rows"]}
    return {
        "scenario_id": alert["scenario_id"],
        "trucks_available": n,
        "truck_allocation": _allocate(n),
        "shelters_open": [s["id"] for s in open_sites],
        "shelters_closed": sorted(closed),
        "shelter_beds_known": beds,
        "shelters_unknown_capacity": [s["id"] for s in open_sites if s["capacity"] is None],
        "shelter_demand": demand,
        "shelter_shortfall_at_median": None if demand is None else max(0, round(demand["median"] - beds)),
        "shelter_shortfall_at_high": None if demand is None else max(0, round(demand["high"] - beds)),
        "staff_note": (f"Jan 2025 deployment: 175 TPW field staff on two 12-hour shifts. TPW budget "
                       f"FY2025-26: {staff['TPW']['fte_fy2026']} FTE; DFR {staff['DFR']['fte_fy2026']} FTE."),
        "method": ("Trucks split across council districts by their share of past winter transport 311 "
                   "requests (largest remainder). Shelter beds = published capacities of open sites; "
                   "sites without a published capacity are listed, not counted."),
        "source": "Processed Dallas tables; City of Dallas memo 2025-01-17; Budget Book FY2025-26; DMN/FOX 4",
    }


def diff_plans(trucks: int | None = None, unavailable_shelters: list[str] | None = None) -> dict:
    before = plan_response()
    after = plan_response(trucks, unavailable_shelters)
    if "error" in after:
        return after
    b = {a["district"]: a["trucks"] for a in before["truck_allocation"]}
    changes = [{"district": a["district"], "trucks_before": b[a["district"]], "trucks_after": a["trucks"],
                "change": a["trucks"] - b[a["district"]]}
               for a in after["truck_allocation"] if a["trucks"] != b[a["district"]]]
    return {
        "scenario_id": after["scenario_id"],
        "baseline": {"trucks_available": before["trucks_available"], "shelters_closed": before["shelters_closed"]},
        "what_if": {"trucks_available": after["trucks_available"], "shelters_closed": after["shelters_closed"]},
        "district_changes": changes,
        "shelter_beds_before": before["shelter_beds_known"],
        "shelter_beds_after": after["shelter_beds_known"],
        "shelter_shortfall_at_median_before": before["shelter_shortfall_at_median"],
        "shelter_shortfall_at_median_after": after["shelter_shortfall_at_median"],
        "source": after["source"],
    }


def get_enso_context() -> dict:
    e = store.climate()["enso_latest"]
    return {k: e[k] for k in ("season", "year", "oni_c", "phase", "strength", "source")}


GUIDANCE_SOURCE = ("NWS winter storm safety (weather.gov/safety/winter-during); "
                   "City of Dallas OEM winter operations")
GUIDANCE = [
    {"keywords": ["indoors", "inside", "travel", "residents", "stay"],
     "text": "Stay inside during the storm; avoid travel unless necessary."},
    {"keywords": ["drive", "driving", "road", "roads", "car", "travel", "ice"],
     "text": "If you must drive, slow down: roads that look only wet can be icy. Keep a winter kit in the car."},
    {"keywords": ["heat", "power", "outage", "warm", "carbon", "generator"],
     "text": "If power or heat goes out, close off unused rooms, block drafts under doors, and never run "
             "generators or grills indoors (carbon monoxide)."},
    {"keywords": ["cold", "frostbite", "hypothermia", "health"],
     "text": "Watch for frostbite and hypothermia; keep moving to stay warm but avoid sweating from overexertion."},
    {"keywords": ["shelter", "homeless", "warming", "311", "transport"],
     "text": "People needing a warm place can call 311 for a ride to a city inclement weather shelter."},
    {"keywords": ["pipes", "water", "freeze", "furnace", "vent"],
     "text": "Keep heating vents and gas furnace intakes clear of snow and ice so the system runs safely."},
]


def retrieve_guidance(topic: str) -> dict:
    words = set(topic.lower().replace("?", " ").split())
    scored = sorted(GUIDANCE, key=lambda g: -len(words & set(g["keywords"])))
    return {"snippets": [g["text"] for g in scored[:2]], "source": GUIDANCE_SOURCE}


def entity_catalog() -> list[dict]:
    """Places, facilities and past storms an answer may name; the trust layer binds numbers to them."""
    county = [{"kind": "county", "key": "48113", "label": COUNTY_NAME, "names": [COUNTY_NAME]}]
    districts = [{"kind": "district", "key": f["properties"]["district"], "label": f"District {f['properties']['district']}",
                  "names": [f"District {f['properties']['district']}", f"Council District {f['properties']['district']}"]}
                 for f in store.districts()["features"]]
    short = {"fair_park": ["Fair Park"], "austin_street": ["Austin Street Center", "Austin Street"],
             "oak_lawn_umc": ["Oak Lawn UMC", "Oak Lawn"], "fair_park_tower": ["Fair Park Tower"]}
    shelters = [{"kind": "shelter", "key": s["id"], "label": s["name"], "names": [s["name"], *short.get(s["id"], [])]}
                for s in _sites()]
    storm_names = {"uri_2021": ["Winter Storm Uri", "Uri"], "ice_2023": ["February 2023 ice storm", "2023 ice storm"],
                   "winter_2025": ["January 2025 winter storm", "January 2025 storm"],
                   "fern_2026": ["Winter Storm Fern", "Fern"], "harvey_2017": ["Hurricane Harvey", "Harvey"]}
    storms = [{"kind": "storm", "key": s["id"], "label": s["name"], "names": [s["name"], *storm_names.get(s["id"], [])]}
              for s in store.storms()]
    return county + districts + shelters + storms


def _schema(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}}


_AMOUNTS = {
    "ice_accretion_in": {"type": "number", "description": "Forecast ice accretion, inches."},
    "min_temp_f": {"type": "number", "description": "Forecast minimum temperature, F."},
    "hours_below_freezing": {"type": "number", "description": "Forecast hours below 32 F."},
    "snowfall_in": {"type": "number", "description": "Forecast snow/sleet, inches."},
}
_WHAT_IF = {
    "trucks": {"type": "integer", "description": "Sanding trucks available, if the user limits them (default 50)."},
    "unavailable_shelters": {"type": "array", "items": {"type": "string"},
                             "description": "Shelters that can't open, by id or name, e.g. [\"Fair Park\"]."},
}

TOOLS = {
    "get_storm_alert": (get_storm_alert, _schema(
        "get_storm_alert",
        "Get the winter storm alert for Dallas County: live NWS alert if one is active, otherwise the "
        "labeled planning scenario (ice, minimum temperature, hours below freezing, snow, lead time). "
        "Call this first in every turn.")),
    "find_similar_storms": (find_similar_storms, _schema(
        "find_similar_storms",
        "Rank past Dallas winter storms by how similar their weather was to this storm, with what each "
        "caused (peak power outages, 311 surges by sector). Amounts default to the alert's.", _AMOUNTS)),
    "get_storm_impacts": (get_storm_impacts, _schema(
        "get_storm_impacts",
        "Details of one past storm: weather, outages, 311 surges, busiest council districts, NOAA events "
        "and narrative, FEMA aid, what the city deployed.",
        {"storm_id": {"type": "string", "description": "e.g. uri_2021, ice_2023, winter_2025, fern_2026, harvey_2017"}},
        ["storm_id"])),
    "estimate_demand": (estimate_demand, _schema(
        "estimate_demand",
        "Estimate demand for this storm as low/median/high ranges from the most similar past storms: "
        "shelter guests per day, storm-driven transport 311 requests (sanding, signals), peak outages, "
        "and transport requests per council district.")),
    "query_assets": (query_assets, _schema(
        "query_assets",
        "List Dallas response assets: inclement weather shelters with capacity, sanding trucks, field "
        "staff, department headcounts (FTE), shelter history, FEMA evacuee shelter capacity.")),
    "plan_response": (plan_response, _schema(
        "plan_response",
        "Build the response plan: sanding trucks per council district and shelter beds vs demand. Turn "
        "what-ifs into arguments and call again.", _WHAT_IF)),
    "diff_plans": (diff_plans, _schema(
        "diff_plans",
        "Compare a what-if plan with the default plan: which districts gain or lose trucks and how "
        "shelter beds and shortfall change. Use the same arguments you gave plan_response.", _WHAT_IF)),
    "get_enso_context": (get_enso_context, _schema(
        "get_enso_context",
        "Current El Niño / La Niña state (NOAA Oceanic Niño Index) for seasonal context.")),
    "retrieve_guidance": (retrieve_guidance, _schema(
        "retrieve_guidance",
        "Official winter safety guidance for residents (NWS, City of Dallas).",
        {"topic": {"type": "string", "description": "What the guidance should cover."}}, ["topic"])),
}

TOOL_SCHEMAS = [schema for _, schema in TOOLS.values()]


def run_tool(name: str, arguments: dict) -> dict:
    if name not in TOOLS:
        return {"error": f"Unknown tool: {name}"}
    fn, schema = TOOLS[name]
    unknown = set(arguments) - set(schema["function"]["parameters"]["properties"])
    if unknown:
        return {"error": f"Unknown arguments for {name}: {sorted(unknown)}"}
    result = fn(**arguments)
    if "error" in result:  # model-correctable, e.g. a wrong storm_id
        return result
    # Engine bug, not a model mistake: raise so it surfaces.
    CONTRACTS[name].model_validate(result)
    return result
