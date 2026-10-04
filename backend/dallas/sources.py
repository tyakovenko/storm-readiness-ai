"""Hand-entered Dallas facts that only exist in documents (memos, briefings, news).

Every value carries its source so tools can cite it and the trust layer can
bind numbers to it. Unknowns stay None — never fill a gap with a guess.
Data-derived tables (311, NOAA, EAGLE-I, weather) are computed in build.py.
"""

FIPS = "48113"
COUNTY = "Dallas County, TX"

MEMO_2025 = "City of Dallas memo 'January 2025, Winter Storm by the Numbers' (2025-01-17)"
OEM_2025 = "Dallas OEM council briefing 'Winter Weather Operations' (2025-11-05)"
FOX4_2024 = "FOX 4 'Dallas opens 2 new homeless inclement weather shelters' (2024-01-14)"
DMN_2026 = "Dallas Morning News 'Dallas officials plan to house over 1,000 at Fair Park' (2026-01-23)"
NBC_2026 = "NBC DFW 'Dallas shares winter weather plan ahead of icy forecast' (2026-01-21)"
PMC_HARVEY = "Harvey mass sheltering surveillance, Dallas County (PMC6255530)"

# Storm windows. `event` = the days the storm disrupted the city (used for impact
# counts); `context` = the wider window of the raw 311 file, whose non-event days
# are the baseline. Dates are local (America/Chicago).
STORMS = [
    {"id": "uri_2021", "name": "Winter Storm Uri", "hazard": "winter",
     "event": ("2021-02-14", "2021-02-20"), "context": ("2021-01-31", "2021-03-07"),
     "fema": ["DR-4586", "EM-3554"]},
    {"id": "ice_2023", "name": "February 2023 ice storm", "hazard": "winter",
     "event": ("2023-01-30", "2023-02-02"), "context": ("2023-01-16", "2023-02-18"),
     "fema": []},
    {"id": "winter_2025", "name": "January 2025 winter storm", "hazard": "winter",
     "event": ("2025-01-09", "2025-01-11"), "context": ("2024-12-26", "2025-01-26"),
     "fema": []},
    {"id": "fern_2026", "name": "Winter Storm Fern (January 2026)", "hazard": "winter",
     "event": ("2026-01-23", "2026-01-27"), "context": ("2026-01-09", "2026-02-11"),
     "fema": []},
    # Not a local hazard: Dallas hosted coastal evacuees. Kept for the evacuee scenario.
    {"id": "harvey_2017", "name": "Hurricane Harvey (evacuee sheltering)", "hazard": "hurricane_evacuees",
     "event": ("2017-08-28", "2017-09-10"), "context": ("2017-08-14", "2017-09-24"),
     "fema": ["DR-4332"]},
]

# What the city actually deployed, per storm. Only documented values.
RESPONSE_FACTS = {
    "winter_2025": [
        {"metric": "tpw_staff", "value": 175, "unit": "people", "note": "two 12-hour shifts", "source": MEMO_2025},
        {"metric": "sanding_trucks", "value": 50, "unit": "trucks", "source": MEMO_2025},
        {"metric": "lane_miles_sanded", "value": 4000, "unit": "lane-miles", "source": MEMO_2025},
        {"metric": "field_personnel", "value": 200, "unit": "people", "note": "'over 200'", "source": MEMO_2025},
        {"metric": "eoc_staff", "value": 27, "unit": "people", "source": MEMO_2025},
        {"metric": "virtual_staff", "value": 180, "unit": "people", "note": "'180+'", "source": MEMO_2025},
        {"metric": "shelter_avg_daily_guests", "value": 950, "unit": "people/day", "note": "4 temporary shelters", "source": MEMO_2025},
        {"metric": "shelter_transport_requests", "value": 237, "unit": "requests", "note": "from Jan 5", "source": MEMO_2025},
        {"metric": "paramedic_crashes", "value": 182, "unit": "crashes", "source": MEMO_2025},
        {"metric": "power_outage_peak_memo", "value": 350, "unit": "outages", "note": "city figure, reduced to 2 by Jan 11", "source": MEMO_2025},
        {"metric": "shelter_stays_activation", "value": 2318, "unit": "stays", "note": "activation Jan 5-13", "source": OEM_2025},
    ],
    "fern_2026": [
        {"metric": "sanding_trucks", "value": 50, "unit": "trucks", "note": "pre-positioned", "source": NBC_2026},
        {"metric": "shelter_planned_guests", "value": 1200, "unit": "people", "note": "'at least 1,200' at Fair Park", "source": DMN_2026},
    ],
    "uri_2021": [
        {"metric": "shelter_cost_usd", "value": 3400000, "unit": "USD", "note": "convention center + hotels, winter 2020-22 incl. Uri", "source": OEM_2025},
    ],
    "harvey_2017": [
        {"metric": "shelter_registered_guests", "value": 3500, "unit": "people", "note": "'more than 3,500' at Kay Bailey Hutchison Convention Center", "source": PMC_HARVEY},
    ],
}

# City-run inclement weather shelter sites (not in FEMA NSS). capacity=None means
# no published number; plans must treat it as unknown, not zero.
SHELTER_SITES = [
    {"id": "fair_park", "name": "Fair Park (Grand Place)", "capacity": 1200,
     "capacity_note": "'at least 1,200' planned Jan 2026", "source": DMN_2026},
    {"id": "fair_park_tower", "name": "Fair Park Tower building", "capacity": None,
     "capacity_note": "used Jan 2025; no published capacity", "source": MEMO_2025},
    {"id": "austin_street", "name": "Austin Street Center (former facility)", "capacity": 360,
     "capacity_note": "2929 Hickory St", "source": FOX4_2024},
    {"id": "oak_lawn_umc", "name": "Oak Lawn United Methodist Church", "capacity": 80,
     "capacity_note": "permitted partner site", "source": FOX4_2024},
]

SHELTER_HISTORY = [
    {"metric": "peak_guests", "value": 1314, "unit": "people", "note": "winter 2023-24, Fair Park + Austin Street", "source": OEM_2025},
    {"metric": "program_cost_fy24_usd", "value": 2900000, "unit": "USD", "note": "budget was 978,000", "source": OEM_2025},
]

# Response resources the planner allocates. Baseline = Jan 2025 documented deployment.
RESOURCES = [
    {"id": "sanding_trucks", "name": "Sanding trucks", "quantity": 50, "unit": "trucks", "department": "TPW", "source": MEMO_2025},
    {"id": "tpw_staff", "name": "Transportation & Public Works field staff", "quantity": 175, "unit": "people per shift", "department": "TPW", "source": MEMO_2025},
]

DEPARTMENTS = {
    "TPW": "Transportation & Public Works (sanding, signals, streets)",
    "DFR": "Dallas Fire-Rescue (EMS, shelter transport)",
    "DPD": "Dallas Police Department",
    "OHS": "Office of Homeless Solutions (shelters)",
    "EMCR": "Office of Emergency Management & Crisis Response (EOC)",
    "DWU": "Dallas Water Utilities",
    "SAN": "Sanitation Services",
    "CCS": "Code Compliance Services (no-heat calls)",
    "DAS": "Dallas Animal Services",
}

# 311 request types -> sector, by substring (case-insensitive). Order matters:
# first match wins. Types not listed are "other" and never count as storm impact.
SECTOR_RULES = [
    ("transport", ["snow/ice", "sanding", "traffic signal", "street repair", "pothole", "barricade", "sign "]),
    ("water", ["water", "wastewater", "sewer", "leak"]),
    ("shelter", ["inclement weather", "homeless", "shelter"]),
    ("heat_housing", ["no heat", "heat"]),
    ("animals_weather", ["lack of care"]),
    ("trees_debris", ["tree", "debris", "limb"]),
]
