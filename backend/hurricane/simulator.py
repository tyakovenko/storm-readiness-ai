"""Hurricane preparedness simulator for response teams (Ask AI -> Simulate).

A firefighter, police officer, council member, transportation crew, EMS/hospital, utility or
emergency-management user picks a US county and a storm -- a live NHC storm, or a hypothetical one
of any category aimed at that county -- and walks a timeline from 3 days out through recovery.

Every number comes from real data or the trained model, never from this module:
  - storm situation per phase: the live NHC forecast track, or a synthetic track built with
    models.scenario_generator (the same ForecastPoint shape the real pipeline consumes),
  - outages for the county and its neighbors: the trained outage model (live_risk.predict_counties),
  - resources and history: FEMA NSS shelters, CMS hospitals, USFA fire registry, EAGLE-I/OpenFEMA,
  - news: live NWS tropical alerts for the county's state.
The role playbooks, community messages, cautions and decision drills are written guidance distilled
from the public agency sources cited with each phase (Ready.gov, NWS/NHC, OSHA, CDC, FEMA).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from .live_feed import get_poller, haversine_nm
from .live_risk import (CUSTOMERS_OUT_PER_TRUCK, county_fire, county_history, county_hospitals, county_shelters,
                        predict_counties)

log = logging.getLogger(__name__)

# ---- sources (cited per phase) ----

SRC = {
    "ready": {"label": "Ready.gov: Hurricanes", "url": "https://www.ready.gov/hurricanes"},
    "evac": {"label": "Ready.gov: Evacuation", "url": "https://www.ready.gov/evacuation"},
    "nws_safety": {"label": "NWS: Hurricane safety", "url": "https://www.weather.gov/safety/hurricane"},
    "nws_ww": {"label": "NWS: Hurricane watches and warnings", "url": "https://www.weather.gov/safety/hurricane-ww"},
    "nhc_prepare": {"label": "NHC: Get prepared", "url": "https://www.nhc.noaa.gov/prepare/"},
    "flood": {"label": "NWS: Turn Around Don't Drown", "url": "https://www.weather.gov/safety/flood-turn-around-dont-drown"},
    "osha": {"label": "OSHA: Hurricane preparedness and response", "url": "https://www.osha.gov/hurricane"},
    "cdc_co": {"label": "CDC: Carbon monoxide poisoning", "url": "https://www.cdc.gov/carbon-monoxide/"},
    "nims": {"label": "FEMA: National Incident Management System", "url": "https://www.fema.gov/emergency-managers/nims"},
    "ipaws": {"label": "FEMA: Public alerts (IPAWS)", "url": "https://www.fema.gov/emergency-managers/practitioners/integrated-public-alert-warning-system"},
}

ROLES = {
    "fire": {"label": "Fire & Rescue", "blurb": "Firefighters, rescue and hazmat crews"},
    "police": {"label": "Law Enforcement", "blurb": "Police, sheriff and public-safety officers"},
    "ems": {"label": "EMS & Hospitals", "blurb": "Ambulance services, hospitals and public health"},
    "transport": {"label": "Transportation & Public Works", "blurb": "Roads, transit, bridges, debris crews"},
    "council": {"label": "City Council & Officials", "blurb": "Mayors, council members, county commissioners"},
    "em": {"label": "Emergency Management", "blurb": "Emergency operations center and coordinators"},
    "utility": {"label": "Utilities", "blurb": "Power, water and communications crews"},
}

# ---- the timeline: hours relative to the storm's closest approach to the county ----

PHASES = [
    {"key": "t72", "offset_h": -72, "title": "3 days out: Monitor and plan",
     "stage": "NHC forecast cone includes your area; watches may follow within a day.",
     "community": "A storm may affect us this week. Check your supplies, refill prescriptions, and look up your evacuation zone now.",
     "cautions": ["Forecast tracks still shift by 100+ miles at this range: plan for the whole cone, not the center line.",
                  "Rumors spread fast: point residents to official county and NWS channels only."],
     "sources": ["nhc_prepare", "ready"],
     "decision": {"question": "The forecast cone covers your county, but the center line passes 80 miles away. What do you do today?",
                  "options": [("Wait for the track to firm up before acting.", False, "Track errors at 3 days are large; teams that wait lose the calm window for staffing, fueling and supply orders."),
                              ("Start readiness steps now: staffing plans, fuel, supplies, and a coordination call.", True, "Right. Low-cost preparation now keeps every option open if the storm turns toward you."),
                              ("Order a full evacuation immediately.", False, "Too early: evacuation orders carry real cost and risk, and over-warning erodes trust. Prepare now, decide with the watch/warning.")]}},
    {"key": "t48", "offset_h": -48, "title": "2 days out: Hurricane watch",
     "stage": "NWS typically issues a Hurricane Watch about 48 hours before tropical-storm-force winds are expected.",
     "community": "A Hurricane Watch is in effect. Finish your plan today: know your zone, where you'd go, and how you'll get there. Help neighbors who may need a ride.",
     "cautions": ["Watch means conditions are possible: use it to finish preparations, not to wait.",
                  "Residents who need help evacuating (medical, mobility, no vehicle) need the most lead time."],
     "sources": ["nws_ww", "evac"],
     "decision": {"question": "A Hurricane Watch is issued. Many residents with medical needs live in a surge-prone area. Your first move?",
                  "options": [("Contact and pre-register residents who need transport or medical support to evacuate.", True, "Right. Special-needs registries and transport take the longest to arrange; start before any order."),
                              ("Wait until an evacuation order is issued to reach them.", False, "That leaves too little time: transport, caregivers and medical shelters need a head start."),
                              ("Tell them to call 911 when the storm arrives.", False, "Responders may be unable to reach anyone once winds pick up. Plan for them now.")]}},
    {"key": "t36", "offset_h": -36, "title": "36 hours out: Warning and evacuations",
     "stage": "NWS typically issues a Hurricane Warning about 36 hours before tropical-storm-force winds; local officials decide evacuation orders.",
     "community": "A Hurricane Warning is in effect. If you are told to evacuate, leave now. Follow the posted routes, take your go-bag and medicines, and bring pets.",
     "cautions": ["Storm surge is the deadliest hurricane hazard: surge-zone evacuations come first.",
                  "Evacuate tens of miles, not hundreds: leave the surge zone, then shelter with friends or at a public shelter.",
                  "Fuel lines and traffic grow fast: keep responders' fuel and routes reserved."],
     "sources": ["nws_ww", "evac", "nws_safety"],
     "decision": {"question": "An evacuation order is issued for surge zones, and some residents say they will stay. What do you do?",
                  "options": [("Keep repeating clear, specific orders through every channel, and record who refuses.", True, "Right. Clear, repeated, multi-channel messages move the most people; knowing who stayed helps rescue later."),
                              ("Promise to rescue anyone who stays during the storm.", False, "Responders cannot operate in hurricane-force winds; that promise encourages people to stay."),
                              ("Stop messaging once the order is issued.", False, "People decide over time; keep the message going until conditions deteriorate.")]}},
    {"key": "t12", "offset_h": -12, "title": "12 hours out: Final preparations",
     "stage": "Tropical-storm-force winds are arriving. Outdoor work and travel get dangerous from here.",
     "community": "Conditions are getting dangerous. If you have not left, stay in a sturdy interior room away from windows. Do not go out in the storm.",
     "cautions": ["Most agencies stop routine response once sustained winds reach about 40-50 mph: set and announce your cutoff.",
                  "Move crews, vehicles and equipment to safe, high ground before the cutoff.",
                  "Never run generators indoors or in garages: carbon monoxide kills."],
     "sources": ["nws_safety", "osha", "cdc_co"],
     "decision": {"question": "Winds are nearing your agency's response cutoff and a non-life-threatening call comes in. What do you do?",
                  "options": [("Send a crew; every call matters.", False, "Crews lost in the storm cannot help anyone afterward. Follow the cutoff."),
                              ("Follow the cutoff: log the call, advise the caller, and respond when winds drop.", True, "Right. Logged calls become the first task list after the storm."),
                              ("Turn off the dispatch phones until the storm passes.", False, "Keep taking and logging calls: they drive the post-storm response.")]}},
    {"key": "t0", "offset_h": 0, "title": "Landfall: Shelter and ride it out",
     "stage": "The storm's closest approach. Highest winds, surge and rain.",
     "community": "Stay inside and away from windows. If the eye passes over, the calm is temporary: do not go out. Call 911 only for life-threatening emergencies.",
     "cautions": ["The eye's calm is temporary; winds return from the opposite direction.",
                  "Track rising water: be ready to move crews and sheltered residents higher.",
                  "Keep a log of calls, damage reports and outages for the first response."],
     "sources": ["nws_safety", "ready"],
     "decision": {"question": "The eye passes over and it's calm. Crews want to head out to calls. What do you do?",
                  "options": [("Go now while it's calm.", False, "The back side of the eyewall can hit within minutes, often with winds just as strong."),
                              ("Hold until the storm has fully passed and winds are below your cutoff.", True, "Right. Wait for the official all-clear on winds before moving."),
                              ("Send just one crew to check conditions.", False, "Even one crew is exposed to the returning eyewall.")]}},
    {"key": "t24p", "offset_h": 24, "title": "Day after: Response and rescue",
     "stage": "Winds have dropped. Flooding, downed lines and blocked roads remain.",
     "community": "Stay off the roads so crews can work. Never drive or walk through flood water. Treat every downed line as live. Run generators outside, away from windows.",
     "cautions": ["Turn Around, Don't Drown: six inches of moving water can knock a person down, a foot can float a car.",
                  "Treat all downed power lines as energized until the utility confirms otherwise.",
                  "Carbon monoxide poisoning from generators spikes after storms.",
                  "Watch crews for heat illness, fatigue and injuries from debris and chainsaws."],
     "sources": ["flood", "osha", "cdc_co"],
     "decision": {"question": "Roads are blocked and calls are backed up. Where do crews go first?",
                  "options": [("Life safety first: rescues, then hospitals, shelters and routes to them.", True, "Right. Clear the routes that unlock life-saving care first, then broaden."),
                              ("Work through calls in the order they arrived.", False, "Triage by life safety, not by time received."),
                              ("Start with the neighborhoods that complain the most.", False, "Priorities should follow life safety and critical facilities.")]}},
    {"key": "t72p", "offset_h": 72, "title": "Days 3+: Recovery",
     "stage": "Power restoration, debris removal, shelters and damage assessment.",
     "community": "Recovery will take time. Share where to find water, food, charging and cooling centers. Report damage to the county. Beware of contractor and aid scams.",
     "cautions": ["Generator and CO incidents, heat illness and chainsaw injuries continue for days after the storm.",
                  "Document damage and costs carefully for state and FEMA reimbursement.",
                  "Rest crews: fatigue drives injuries in long recoveries."],
     "sources": ["ready", "osha", "nims"],
     "decision": {"question": "Power will be out for days in some areas. What helps residents most right now?",
                  "options": [("Open cooling/charging centers and publish where to get water, food and help.", True, "Right. Practical, local information and places to go reduce health risks during long outages."),
                              ("Wait for full restoration estimates before saying anything.", False, "Share what you know now and update often; silence fuels rumors."),
                              ("Tell residents to run generators indoors when it rains.", False, "Never: indoor generators cause carbon monoxide deaths.")]}},
]

# Role playbooks: what each team does in each phase. Written guidance, not data.
PLAYBOOK = {
    "fire": {
        "t72": ["Check staffing for 12-hour shifts and plan who covers when crews are sheltering.",
                "Fuel every apparatus and generator; stock water-rescue gear, chainsaws and PPE.",
                "Confirm mutual-aid and water-rescue agreements with neighboring departments."],
        "t48": ["Pre-identify flood-prone areas and high-ground staging spots for apparatus.",
                "Brief crews on the wind cutoff for response and on water-rescue procedures.",
                "Check generators and fuel at every station; secure loose equipment."],
        "t36": ["Support surge-zone evacuations: door-to-door where ordered, assist mobility-limited residents.",
                "Pre-position rescue boats and high-water vehicles outside the surge zone.",
                "Coordinate with EMS on transfers from nursing homes and hospitals in the zone."],
        "t12": ["Move apparatus to hardened stations or staging away from surge and falling trees.",
                "Announce the response cutoff; switch dispatch to call-logging.",
                "Top off fuel and water; get crews rested before the storm."],
        "t0": ["Shelter in place; log calls by priority for after the storm.",
               "Monitor rising water around stations; be ready to relocate.",
               "Keep radio check-ins on schedule; account for every crew."],
        "t24p": ["Start search and rescue in the hardest-hit and flooded areas first.",
                 "Clear access to hospitals, shelters and critical facilities with public works.",
                 "Watch for gas leaks, fires from downed lines, and generator CO calls."],
        "t72p": ["Rotate crews; bring in mutual aid for long operations.",
                 "Do damage and hazard assessments of homes and businesses.",
                 "Track overtime, equipment and costs for reimbursement."],
    },
    "police": {
        "t72": ["Plan 12-hour shifts and backup staffing; check vehicles, radios and fuel.",
                "Review evacuation traffic plans and contraflow procedures with transportation.",
                "Coordinate with jails and holding facilities on evacuation plans."],
        "t48": ["Pre-assign traffic posts for evacuation routes and fuel stations.",
                "Plan security for shelters and critical sites.",
                "Help push watch messaging through community and social channels."],
        "t36": ["Run evacuation traffic control and keep emergency lanes open.",
                "Patrol evacuated areas to deter looting while it is safe.",
                "Record residents who refuse to evacuate for later welfare checks."],
        "t12": ["Close dangerous roads, bridges and causeways as winds rise.",
                "Move vehicles and staff to safe locations before the cutoff.",
                "Keep a skeleton crew at shelters and the operations center."],
        "t0": ["Shelter in place; take and log calls for after the storm.",
               "Maintain communications with the emergency operations center.",
               "Monitor jails and shelters for flooding or damage."],
        "t24p": ["Control traffic around damage, downed lines and flooded roads.",
                 "Secure damaged neighborhoods and business districts.",
                 "Run welfare checks on residents who stayed behind."],
        "t72p": ["Enforce curfews if ordered; watch for fraud and price gouging.",
                 "Support distribution sites with traffic and security.",
                 "Keep patrols visible in recovering neighborhoods."],
    },
    "ems": {
        "t72": ["Review hospital census and plan transfers for patients at risk.",
                "Stock medications, oxygen, fuel and backup power supplies.",
                "Identify home-health and dialysis patients who will need support."],
        "t48": ["Confirm generator tests and fuel contracts at hospitals and clinics.",
                "Coordinate medical-needs shelter staffing and supplies.",
                "Plan ambulance staging outside the surge zone."],
        "t36": ["Evacuate nursing homes and patients in surge zones as ordered.",
                "Activate medical-needs shelters; brief staff on CO and heat risks.",
                "Pre-position ambulances and supplies on safe ground."],
        "t12": ["Move ambulances to hardened locations before the response cutoff.",
                "Hospitals go to storm staffing: lock-in teams and supplies.",
                "Confirm backup communications with dispatch and hospitals."],
        "t0": ["Shelter crews; keep hospitals on generator and storm staffing.",
               "Log emergency calls for response after the storm.",
               "Watch power and water at hospitals; be ready to relocate patients."],
        "t24p": ["Respond to injuries from debris, chainsaws, CO and heat.",
                 "Check on dialysis, oxygen and home-health patients.",
                 "Track hospital capacity and divert as needed."],
        "t72p": ["Support shelter health, sanitation and disease prevention.",
                 "Watch for CO poisoning, heat illness and wound infections.",
                 "Resume normal services as hospitals and roads recover."],
    },
    "transport": {
        "t72": ["Inspect and clear storm drains, culverts and pump stations.",
                "Fuel vehicles; stage barricades, signs and debris equipment.",
                "Review evacuation routes and contraflow plans with law enforcement."],
        "t48": ["Coordinate transit buses for residents without vehicles.",
                "Secure construction sites and loose materials on the roadways.",
                "Pre-position debris and chainsaw crews outside the surge zone."],
        "t36": ["Run evacuation transit and support contraflow if ordered.",
                "Post route signage and keep fuel stations on evacuation routes supplied.",
                "Plan when bridges and causeways close as winds rise."],
        "t12": ["Close bridges and causeways at the wind threshold.",
                "Move equipment and vehicles to high ground.",
                "Stop transit service once it is no longer safe."],
        "t0": ["Shelter crews; monitor pump stations and flooding remotely.",
               "Log road closures and damage reports.",
               "Plan the first routes to clear after the storm."],
        "t24p": ["Clear routes to hospitals, shelters and fire stations first.",
                 "Barricade flooded roads and damaged bridges; inspect before reopening.",
                 "Work with the utility before clearing debris tangled with power lines."],
        "t72p": ["Run debris removal and keep records for reimbursement.",
                 "Restore traffic signals and signage.",
                 "Resume transit and support distribution sites."],
    },
    "council": {
        "t72": ["Confirm who has authority to declare an emergency and order evacuations.",
                "Join the emergency management coordination calls.",
                "Agree on one public spokesperson and one message."],
        "t48": ["Prepare a local emergency declaration to speed help and spending.",
                "Amplify official messages through your channels, in every local language.",
                "Make sure vulnerable residents and businesses get the word."],
        "t36": ["Back evacuation orders publicly and clearly; avoid mixed messages.",
                "Approve emergency spending and shelter use as needed.",
                "Coordinate with state officials on resources and requests."],
        "t12": ["Shelter safely; stay reachable for decisions.",
                "Keep sharing only official updates.",
                "Avoid travel into dangerous areas, including for media visits."],
        "t0": ["Stay sheltered and reachable.",
               "Support the emergency operations center's decisions.",
               "Prepare messages for the first morning after the storm."],
        "t24p": ["Share where residents can get help, water, food and shelter.",
                 "Request state and federal assistance through emergency management.",
                 "Visit only when it won't slow response crews."],
        "t72p": ["Push for a fair, visible recovery plan and timeline.",
                 "Help residents with aid applications and warn about scams.",
                 "Hold an after-action review to improve the next response."],
    },
    "em": {
        "t72": ["Activate the emergency operations center at the right level and start coordination calls.",
                "Check shelter readiness, supplies and staffing.",
                "Review your evacuation zones against the forecast."],
        "t48": ["Recommend evacuation timing to officials; prepare orders.",
                "Open the special-needs registry outreach and transport plan.",
                "Pre-stage commodities and request state resources early."],
        "t36": ["Issue evacuation orders and open shelters.",
                "Send alerts through wireless emergency alerts, media and social.",
                "Track shelter populations and resource requests."],
        "t12": ["Set the response cutoff and confirm all crews are sheltered.",
                "Keep the operations center staffed and powered.",
                "Prepare post-storm damage assessment teams."],
        "t0": ["Maintain situational awareness and logs.",
               "Monitor shelters, hospitals and critical facilities.",
               "Plan the first operational period after landfall."],
        "t24p": ["Run rapid damage assessments and set priorities.",
                 "Coordinate search and rescue, debris and utility restoration.",
                 "Open distribution points and cooling/charging centers."],
        "t72p": ["Shift from response to recovery; document everything for FEMA.",
                 "Support residents with aid information and shelter transitions.",
                 "Run the after-action review."],
    },
    "utility": {
        "t72": ["Pre-arrange mutual-aid crews and staging sites outside the storm's path.",
                "Stock poles, transformers, wire and fuel.",
                "Review priority restoration lists: hospitals, water plants, 911."],
        "t48": ["Confirm crew lodging, food and fuel at staging sites.",
                "Check generators at substations, water and wastewater plants.",
                "Tell medical-needs customers to plan for long outages."],
        "t36": ["Move mutual-aid crews to staging outside the storm's path.",
                "Secure equipment and top off fuel.",
                "Publish outage reporting and safety messages."],
        "t12": ["Pull crews from the field before the wind cutoff.",
                "Plan the first damage patrols for after the storm.",
                "Keep the outage map and call center running."],
        "t0": ["Crews shelter; track outages remotely.",
               "Keep water and wastewater plants on backup power.",
               "Prepare damage assessment teams."],
        "t24p": ["Assess damage and restore hospitals, water and 911 first.",
                 "Make downed lines safe; coordinate with debris crews.",
                 "Give honest restoration estimates by area."],
        "t72p": ["Bring in mutual aid for the long restoration.",
                 "Restore the largest customer groups next, then individual homes.",
                 "Remind residents about generator safety while outages last."],
    },
}

# ---- hypothetical storm settings ----

CATEGORIES = {  # max wind (kt) and typical quadrant wind radii (nm) for that strength: a stated assumption
    "ts": {"label": "Tropical Storm", "kt": 55, "radii": {34: (110, 90, 80, 90)}},
    "1": {"label": "Category 1", "kt": 75, "radii": {64: (25, 20, 15, 20), 50: (50, 40, 35, 40), 34: (120, 100, 90, 100)}},
    "2": {"label": "Category 2", "kt": 90, "radii": {64: (30, 25, 20, 25), 50: (60, 50, 40, 50), 34: (130, 110, 100, 110)}},
    "3": {"label": "Category 3", "kt": 105, "radii": {64: (35, 30, 25, 30), 50: (70, 55, 45, 55), 34: (140, 120, 110, 120)}},
    "4": {"label": "Category 4", "kt": 125, "radii": {64: (40, 35, 30, 35), 50: (80, 65, 55, 65), 34: (150, 130, 120, 130)}},
    "5": {"label": "Category 5", "kt": 145, "radii": {64: (45, 40, 35, 40), 50: (90, 75, 60, 75), 34: (160, 140, 130, 140)}},
}
APPROACHES = {"south": ("From the south", 0.0), "southeast": ("From the southeast", 315.0),
              "southwest": ("From the southwest", 45.0), "east": ("From the east", 270.0),
              "west": ("From the west", 90.0)}
OFFSETS = {"direct": ("Direct hit", 0.0), "west": ("Center passes 40 nm west (your county on the stronger side)", -40.0),
           "east": ("Center passes 40 nm east (your county on the weaker side)", 40.0)}
FORWARD_SPEED_KT = 12.0
NEIGHBOR_RADIUS_NM = 80.0
MAX_NEIGHBORS = 7


SAFFIR_SIMPSON_KT = [(137, "Category 5"), (113, "Category 4"), (96, "Category 3"), (83, "Category 2"),
                     (64, "Category 1"), (34, "Tropical Storm")]


def _cat_label(kt: float) -> str:
    return next((label for floor, label in SAFFIR_SIMPSON_KT if kt >= floor), "Tropical Depression")


def setup() -> dict:
    return {
        "roles": [{"id": k, **v} for k, v in ROLES.items()],
        "categories": [{"id": k, "label": v["label"], "max_wind_kt": v["kt"]} for k, v in CATEGORIES.items()],
        "approaches": [{"id": k, "label": v[0]} for k, v in APPROACHES.items()],
        "offsets": [{"id": k, "label": v[0]} for k, v in OFFSETS.items()],
        "lead_times_h": [72, 48, 24],
        "coverage": "US counties (the outage model and the shelter, hospital and fire data are US-wide). "
                    "The phase guidance applies to any coastal community in North America.",
    }


def search_counties(q: str, limit: int = 12) -> list[dict]:
    from models.pipeline import get_name_lookup
    from .live_risk import county_key
    key = county_key(q.split(",")[0])
    st = q.split(",")[1].strip().upper()[:2] if "," in q else ""
    if not key:
        return []
    hits = []
    for fips, c in get_name_lookup().items():
        name = county_key(c.get("name", ""))
        if name.startswith(key) and (not st or c.get("state") == st):
            hits.append((name != key, -(c.get("population") or 0), fips, c))
    hits.sort()
    return [{"fips": f, "name": c["name"], "state": c["state"], "population": c.get("population")} for *_, f, c in hits[:limit]]


# ---- building a simulation ----

def _synthetic_points(county_lat: float, county_lon: float, category: str, approach: str, offset: str, hours: int):
    """Constant-heading synthetic track whose closest approach to the county is at tau = hours."""
    from models.county_geometry import bearing_deg, destination_point
    from models.scenario_generator import ScenarioConfig, ScenarioWindRadii, generate_scenario_forecast_points
    heading = APPROACHES[approach][1]
    off = OFFSETS[offset][1]
    # Closest-approach point: the county, shifted perpendicular to the track (negative = west/left of travel).
    if off:
        ca = destination_point(county_lat, county_lon, (heading + (90 if off > 0 else -90)) % 360, abs(off))
    else:
        ca = (county_lat, county_lon)
    start = destination_point(ca[0], ca[1], (heading + 180) % 360, FORWARD_SPEED_KT * hours)
    # Great circles bend in compass terms: aim the start at the closest-approach point so the track
    # passes exactly through it at tau = hours.
    heading = bearing_deg(start[0], start[1], ca[0], ca[1])
    cat = CATEGORIES[category]
    taus = tuple(sorted({0, 12, 24, 36, 48, 60, 72, hours + 24, hours + 48, hours + 72}))  # T-72 to T+72
    cfg = ScenarioConfig(
        storm_name="SIMULATED", basin="AL", cyclone_num=91,
        cycle_init_time_utc=datetime(2026, 8, 28, 6, 0, 0),  # inside a published ONI season (see scenario_generator)
        start_lat=start[0], start_lon=start[1], heading_deg=heading, forward_speed_kt=FORWARD_SPEED_KT,
        max_wind_kt=float(cat["kt"]), mslp_mb=1000.0 - cat["kt"] * 0.5, storm_type="HU" if cat["kt"] >= 64 else "TS",
        wind_radii_kt={t: ScenarioWindRadii(*r) for t, r in cat["radii"].items()}, tau_values_h=taus)
    return generate_scenario_forecast_points(cfg)


def _position_at(points: list, when: datetime):
    """Linear interpolation along the forecast points; None outside their time span."""
    as_utc = lambda dt: dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    pts = sorted(points, key=lambda p: p.valid_time_utc)
    for a, b in zip(pts, pts[1:]):
        ta, tb = as_utc(a.valid_time_utc), as_utc(b.valid_time_utc)
        if ta <= when <= tb:
            f = (when - ta) / (tb - ta) if tb > ta else 0
            return a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f, a.vmax_kt + (b.vmax_kt - a.vmax_kt) * f, a
    return None


def _ts_radius_nm(point) -> float | None:
    r = (getattr(point, "wind_radii", None) or {}).get(34)
    return max(r.ne_nm, r.se_nm, r.sw_nm, r.nw_nm) if r else None


def _resource_lines(phase_key: str, res: dict, impact: dict | None) -> list[str]:
    """Named, real resources that matter in this phase."""
    sh, ho, fi, hi = res["shelters"], res["hospitals"], res["fire"], res["history"]
    safe = [s for s in sh.get("top", []) if not s.get("in_surge_zone")]
    lines = []
    if phase_key in ("t48", "t36") and safe:
        lines.append("Largest shelters outside the surge zone: " + "; ".join(
            f"{s['name']} ({s['city']}, {s['evacuation_capacity']:,} beds{', generator' if s['generator'] else ''})" for s in safe[:3]))
    if phase_key in ("t72", "t36", "t24p") and ho.get("top"):
        er = [h for h in ho["top"] if h["emergency_services"]]
        if er:
            lines.append("Hospitals with an emergency department: " + "; ".join(f"{h['name']} ({h['city']})" for h in er[:4]))
    if phase_key in ("t72", "t24p") and fi.get("top"):
        lines.append("Largest fire departments: " + "; ".join(
            f"{d['name']} ({d['stations']} stations, {d['career']} career / {d['volunteer']} volunteer)" for d in fi["top"][:3]))
    if phase_key in ("t72", "t72p") and impact:
        t = impact["trucks_needed"]
        lines.append(f"Utility trucks to plan for: {t['low']}-{t['high']} (median {t['median']}), at 1 truck per "
                     f"{CUSTOMERS_OUT_PER_TRUCK:,} predicted customers out")
    if phase_key == "t72" and hi.get("worst"):
        w = hi["worst"][0]
        lines.append(f"Worst past outage here: {w['storm']} {w['year']}, {w['peak_customers_out']:,} customers "
                     f"({w['pct_customers_out']}%)")
    return lines


def build(role: str, fips: str, mode: str = "hypothetical", storm_id: str | None = None, category: str = "3",
          approach: str = "south", offset: str = "direct", hours_to_landfall: int = 72) -> dict:
    """Raises KeyError for an unknown role/county/storm, ValueError for a bad setting."""
    from models.pipeline import get_name_lookup, get_static_tables
    if role not in ROLES:
        raise KeyError(f"role {role!r}")
    static = get_static_tables()
    cent = static["centroids"]
    row = cent.loc[cent["county_fips"] == fips]
    info = get_name_lookup().get(fips)
    if row.empty or not info:
        raise KeyError(f"county {fips!r}")
    clat, clon = float(row.iloc[0]["county_lat"]), float(row.iloc[0]["county_lon"])
    now = datetime.now(timezone.utc)
    assumptions = [f"ASSUMPTION: 1 utility truck per {CUSTOMERS_OUT_PER_TRUCK:,} predicted customers out (planning rule of thumb)."]
    skipped: list = []

    if mode == "live":
        poller = get_poller()
        storm = next((s for s in poller.get_active_storms() if s["storm_id"] == (storm_id or "").upper()), None)
        if storm is None:
            raise KeyError(f"storm {storm_id!r} is not active")
        pts = poller.get_forecast_points(storm["storm_id"])
        as_utc = lambda dt: dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        snap = min(pts, key=lambda p: haversine_nm(clat, clon, p.lat, p.lon))
        closest = as_utc(snap.valid_time_utc)
        anchor = closest
        storm_info = {"kind": "live", "name": storm["name"], "storm_id": storm["storm_id"],
                      "label": f"{_cat_label(storm['intensity_kt'])} {storm['name']}", "max_wind_kt": storm["intensity_kt"],
                      "closest_approach_nm": round(haversine_nm(clat, clon, snap.lat, snap.lon)),
                      "closest_approach_utc": closest.isoformat(), "source": "NOAA NHC official forecast (live)"}
        advisory = {"storm_id": storm["storm_id"], "storm_name": storm["name"], "advisory_number": 0}
        tau = snap.tau_h
    else:
        if category not in CATEGORIES or approach not in APPROACHES or offset not in OFFSETS:
            raise ValueError("unknown category, approach or offset")
        hours = int(hours_to_landfall)
        if hours not in (24, 48, 72):
            raise ValueError("hours_to_landfall must be 24, 48 or 72")
        # The track always starts 72 h out so every phase has a storm position; hours_to_landfall picks
        # the phase the exercise opens on.
        pts = _synthetic_points(clat, clon, category, approach, offset, 72)
        tau = 72
        anchor = pts[0].cycle_init_time_utc.replace(tzinfo=timezone.utc) + timedelta(hours=72)
        cat = CATEGORIES[category]
        storm_info = {"kind": "hypothetical", "name": "Simulated storm", "label": f"Simulated {cat['label']} hurricane"
                      if category != "ts" else "Simulated tropical storm", "max_wind_kt": cat["kt"],
                      "max_wind_mph": round(cat["kt"] * 1.15078), "approach": APPROACHES[approach][0],
                      "track": OFFSETS[offset][0], "hours_to_landfall": hours,
                      "closest_approach_nm": abs(int(OFFSETS[offset][1])),
                      "source": "Synthetic track (models/scenario_generator.py) through the real outage model"}
        advisory = {"storm_id": pts[0].storm_id, "storm_name": "SIMULATED", "advisory_number": 0}
        assumptions += [f"Hypothetical storm: constant {FORWARD_SPEED_KT:.0f} kt forward speed and constant intensity "
                        "(no weakening over land), with typical wind-field sizes for its category.",
                        "Phases are timed from the storm's closest approach to the county."]

    # The county and its nearest neighbors through the trained model at the closest-approach snapshot.
    near = sorted(((haversine_nm(clat, clon, r.county_lat, r.county_lon), r.county_fips) for r in cent.itertuples()
                   if r.county_fips != fips and abs(r.county_lat - clat) < 2 and abs(r.county_lon - clon) < 2.5))
    neighbors = [f for d, f in near if d <= NEIGHBOR_RADIUS_NM][:MAX_NEIGHBORS]
    preds = {c["fips"]: c for c in predict_counties([fips] + neighbors, advisory, pts, tau, skipped)}
    impact = preds.get(fips)
    if impact and storm_info["kind"] == "hypothetical":
        impact["caveat"] = "Model run on a hypothetical storm for training: a planning signal, not a forecast."

    resources = {"shelters": county_shelters(info["state"], info["name"]),
                 "hospitals": county_hospitals(info["state"], info["name"]),
                 "fire": county_fire(info["state"], info["name"]), "history": county_history(fips)}

    try:
        alerts = [a for a in get_poller().get_active_alerts()
                  if any(str(u).upper().startswith(info["state"]) for u in a.get("ugc_codes") or [])]
    except Exception:
        alerts = []

    phases = []
    for ph in PHASES:
        when = anchor + timedelta(hours=ph["offset_h"])
        pos = _position_at(pts, when)
        situation = None
        if pos:
            lat, lon, kt, seg = pos
            dist = round(haversine_nm(clat, clon, lat, lon))
            r34 = _ts_radius_nm(seg)
            situation = {"distance_nm": dist, "storm_wind_kt": round(kt), "storm_label": _cat_label(kt),
                         "ts_winds_at_county": None if r34 is None else dist <= r34}
        status = None
        if storm_info["kind"] == "live":
            status = "past" if when + timedelta(hours=6) < now else ("now" if when - timedelta(hours=6) <= now else "upcoming")
        phases.append({
            "key": ph["key"], "offset_h": ph["offset_h"], "title": ph["title"], "stage": ph["stage"],
            "when": f"{when:%a %b} {when.day}, {when:%H:%M} UTC" if storm_info["kind"] == "live" else None,
            "status": status, "situation": situation,
            "actions": PLAYBOOK[role][ph["key"]], "community_message": ph["community"], "cautions": ph["cautions"],
            "resources": _resource_lines(ph["key"], resources, impact),
            "decision": {"question": ph["decision"]["question"],
                         "options": [{"text": t, "correct": c, "feedback": f} for t, c, f in ph["decision"]["options"]]},
            "sources": [SRC[s] for s in ph["sources"]],
        })

    return {
        "role": {"id": role, **ROLES[role]},
        "county": {"fips": fips, "name": info["name"], "state": info["state"], "population": info.get("population"),
                   "customers_served": info.get("customers_served"), "svi": info.get("svi_overall"),
                   "high_social_vulnerability": (info.get("svi_overall") or 0) >= 0.65, "lat": clat, "lon": clon},
        "storm": storm_info,
        "impact": impact,
        "region": sorted(({"fips": c["fips"], "name": c["name"], "state": c["state"], "risk_tier": c["risk_tier"],
                           "customers_out": c["customers_out"]} for f, c in preds.items() if f != fips),
                         key=lambda c: -c["customers_out"]["median"]),
        "resources": resources,
        "alerts": {"state": info["state"], "count": len(alerts),
                   "items": [{"event": a["event"], "area": (a.get("area_desc") or "")[:200]} for a in alerts[:6]],
                   "source": "NWS Active Alerts API (live)"},
        "phases": phases,
        "start_phase": next((p["key"] for p in phases if p["status"] == "now"), phases[0]["key"]) if storm_info["kind"] == "live"
        else [p["key"] for p in PHASES if p["offset_h"] <= -int(hours_to_landfall)][-1],  # the last phase already reached
        "skipped": skipped,
        "assumptions": assumptions,
        "generated_utc": now.isoformat(timespec="seconds"),
    }
