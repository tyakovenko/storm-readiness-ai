"""Fake data for the demo. Every value here is made up.

Workstream A (data & impact model) and B (scenarios & optimization) replace
this file with real engines. Keep the output shapes in tools.py the same and
the agent, trust layer and UI keep working unchanged.
"""

STUB_SOURCE = "STUB demo data (not a real forecast)"
IMPACT_MODEL_VERSION = "stub-impact-v0"

ADVISORY = {
    "storm_id": "AL992026",
    "storm_name": "Demo Storm Alpha",
    "basin": "AL",
    "advisory_number": 14,
    "issued_utc": "2026-09-27T15:00Z",
    "category": 3,
    "max_wind_kt": 105,
    "lead_time_to_landfall_h": 72,
    "forecast_landfall": "Florida Big Bend coast",
    "source": f"{STUB_SOURCE}; stands in for the NHC advisory",
}

SCENARIOS = {
    "n_scenarios": 50,
    "lead_time_h": 72,
    "landfall_spread_nm": 80,
    "pct_scenarios_landfall_west_of_forecast": 36,
    "method": "stub; AR(1) forecast-error scenarios pending (Workstream B)",
    "source": STUB_SOURCE,
}

ENSO = {
    "season": "JAS",
    "year": 2026,
    "oni_c": 1.4,
    "phase": "El Niño",
    "strength": "moderate",
    "source": f"{STUB_SOURCE}; stands in for the NOAA CPC Oceanic Niño Index",
}

# FIPS codes are real 5-digit strings; every other number is invented.
COUNTIES = [
    {
        "fips": "12075",
        "name": "Levy County",
        "state": "FL",
        "customers_served": 24000,
        "vulnerable_population": 9800,
        "pct_customers_out": {"low": 38, "median": 55, "high": 71},
        "risk_tier": "red",
        "truckloads_needed": 5,
        "why": ["Closest to the forecast landfall point", "Mostly overhead power lines"],
    },
    {
        "fips": "12029",
        "name": "Dixie County",
        "state": "FL",
        "customers_served": 9100,
        "vulnerable_population": 4300,
        "pct_customers_out": {"low": 30, "median": 47, "high": 66},
        "risk_tier": "red",
        "truckloads_needed": 3,
        "why": ["Inside the scenario spread in most scenarios", "High social vulnerability"],
    },
    {
        "fips": "12017",
        "name": "Citrus County",
        "state": "FL",
        "customers_served": 88000,
        "vulnerable_population": 21500,
        "pct_customers_out": {"low": 18, "median": 31, "high": 49},
        "risk_tier": "orange",
        "truckloads_needed": 4,
        "why": ["Large customer base on the storm's stronger right side"],
    },
    {
        "fips": "12123",
        "name": "Taylor County",
        "state": "FL",
        "customers_served": 11200,
        "vulnerable_population": 3900,
        "pct_customers_out": {"low": 12, "median": 24, "high": 40},
        "risk_tier": "yellow",
        "truckloads_needed": 2,
        "why": ["Hit only in the western scenarios"],
    },
]

TRUCKS_AVAILABLE = 10
STAGING_AREA = "Gainesville staging area"

# FEMA ESF #6 shape. "id" is what users say in what-ifs ("Shelter 2 is closed").
SHELTERS = [
    {"id": "Shelter 1", "name": "Levy demo shelter A", "county_fips": "12075",
     "lat": 29.45, "lon": -82.64, "evacuation_capacity": 400, "post_impact_capacity": 250,
     "status": "open", "generator": True, "wheelchair_accessible": True, "pets_allowed": False,
     "in_surge_zone": False},
    {"id": "Shelter 2", "name": "Citrus demo shelter A", "county_fips": "12017",
     "lat": 28.90, "lon": -82.59, "evacuation_capacity": 900, "post_impact_capacity": 600,
     "status": "open", "generator": True, "wheelchair_accessible": True, "pets_allowed": True,
     "in_surge_zone": False},
    {"id": "Shelter 3", "name": "Citrus demo shelter B", "county_fips": "12017",
     "lat": 28.85, "lon": -82.49, "evacuation_capacity": 450, "post_impact_capacity": 300,
     "status": "open", "generator": False, "wheelchair_accessible": True, "pets_allowed": False,
     "in_surge_zone": False},
    {"id": "Shelter 4", "name": "Dixie demo shelter A", "county_fips": "12029",
     "lat": 29.63, "lon": -83.13, "evacuation_capacity": 250, "post_impact_capacity": 150,
     "status": "open", "generator": None, "wheelchair_accessible": None, "pets_allowed": None,
     "in_surge_zone": None},
    {"id": "Shelter 5", "name": "Taylor demo shelter A", "county_fips": "12123",
     "lat": 30.12, "lon": -83.58, "evacuation_capacity": 300, "post_impact_capacity": 200,
     "status": "open", "generator": True, "wheelchair_accessible": False, "pets_allowed": False,
     "in_surge_zone": True},
]

# Bhattarai & Song assumption (CLAUDE.md rule 7): must be labeled as an assumption.
SHELTER_DEMAND_PCT_OF_VULNERABLE = 5

ANALOGS = [
    {"storm": "Stub analog storm A", "year": 2016, "enso_phase": "El Niño", "similarity": 0.82,
     "peak_pct_customers_out_median": 42},
    {"storm": "Stub analog storm B", "year": 2004, "enso_phase": "Neutral", "similarity": 0.77,
     "peak_pct_customers_out_median": 58},
    {"storm": "Stub analog storm C", "year": 1998, "enso_phase": "El Niño", "similarity": 0.71,
     "peak_pct_customers_out_median": 33},
]

GUIDANCE = [
    {"keywords": ["water", "food", "supplies", "kit", "prepare", "residents"],
     "text": "Build a kit with water (1 gallon per person per day, for several days), food, medicine and a flashlight."},
    {"keywords": ["evacuate", "evacuation", "leave", "zone", "residents"],
     "text": "Know your evacuation zone and leave when local officials tell you to."},
    {"keywords": ["power", "generator", "outage", "carbon"],
     "text": "Run generators outdoors only, away from windows, to avoid carbon monoxide poisoning."},
    {"keywords": ["shelter", "pets", "medical"],
     "text": "Check which public shelters are open and whether they accept pets or medical needs."},
]
GUIDANCE_SOURCE = "STUB paraphrase of FEMA / Ready.gov guidance; real retrieval index pending"
