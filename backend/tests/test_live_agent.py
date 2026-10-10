"""Tests for the live-storms Ask AI agent (agent/live_adk.py) and its routing."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import backend.app  # noqa: F401  (puts backend/ on sys.path, like the other agent tests)
from agent import landing_router, live_adk
from hurricane import live_feed, live_risk

STORM = {"storm_id": "AL092026", "name": "Isaias", "classification": "HU", "intensity_kt": 100.0, "pressure_mb": 959.0,
         "lat": 29.2, "lon": -87.0, "movement_dir_deg": 10, "movement_speed_mph": 17,
         "last_update_utc": "2026-10-09T21:00:00.000Z", "advisory_num": "013", "public_advisory_url": None}
CYCLE = datetime(2026, 10, 9, 18, tzinfo=timezone.utc)
POINTS = [SimpleNamespace(cycle_init_time_utc=CYCLE, tau_h=t, valid_time_utc=CYCLE + timedelta(hours=t), lat=la, lon=lo, vmax_kt=v)
          for t, la, lo, v in [(0, 28.5, -87.1, 105.0), (12, 31.2, -86.8, 75.0), (24, 33.4, -87.2, 40.0)]]
RNG = lambda lo, med, hi: {"low": lo, "median": med, "high": hi}
RISK = {
    "storm_id": "AL092026", "storm_name": "Isaias", "forecast_cycle_utc": CYCLE.isoformat(), "risk_radius_nm": 120.0,
    "counties_evaluated": 1, "skipped": [], "caveats": [], "assumptions": ["ASSUMPTION: 1 utility truck per 2,000 predicted customers out."],
    "model_source": "Test model", "trucks_needed_total": RNG(27, 38, 68),
    "staging": {"fips": "12073", "name": "Leon County, FL staging area", "county": "Leon County", "state": "FL",
                "lat": 30.46, "lon": -84.28, "clearance_from_track_nm": 136, "avg_distance_to_counties_nm": 110, "method": "Test"},
    "counties": [{
        "fips": "01003", "name": "Baldwin County", "state": "AL", "lat": 30.66, "lon": -87.75, "risk_tier": "orange",
        "pct_customers_out": RNG(27.0, 38.9, 69.0), "customers_served": 195253, "customers_out": RNG(52718, 75953, 134725),
        "why": ["Strong winds"], "distance_to_track_nm": 48, "closest_forecast_utc": (CYCLE + timedelta(hours=12)).isoformat(),
        "forecast_wind_kt_at_closest": 75.0, "trucks_needed": RNG(27, 38, 68),
        "shelters": {"count": 15, "evacuation_capacity": 4846, "with_generator": 6, "in_surge_zone": 2, "top": [], "source": "FEMA NSS"},
        "hospitals": {"count": 4, "with_emergency_dept": 3, "top": [], "source": "CMS"},
        "fire": {"departments": 26, "stations": 49, "career_firefighters": 229, "volunteer_firefighters": 567,
                 "paid_per_call_firefighters": 36, "top": [], "source": "USFA"},
        "history": {"storms_with_outages": 6, "worst": [{"storm": "Sally", "year": 2020, "peak_customers_out": 126286, "pct_customers_out": 80.1}],
                    "fema_declarations": 23, "recent_declarations": [], "source": "EAGLE-I"},
        "pack_slug": None}],
}


@pytest.fixture
def live_data():
    poller = live_feed.get_poller()
    with patch.object(poller, "get_active_storms", return_value=[STORM]), \
         patch.object(poller, "get_forecast_points", return_value=POINTS), \
         patch.object(poller, "poll", return_value={"last_polled_utc": "2026-10-09T21:10:00+00:00", "active_tropical_alerts_count": 7}), \
         patch.object(poller, "get_active_alerts", return_value=[]), \
         patch.dict(live_risk._cache, {"AL092026": (9e18, RISK)}, clear=True):
        yield


@pytest.mark.parametrize("q, strict, expected", [
    ("Where is Isaias headed?", True, True),                 # names an active storm
    ("Which storms are active right now?", True, True),
    ("What's the current shelter plan?", True, False),       # on a county page: about that scenario
    ("What's the current outage risk?", False, True),        # home page: nothing selected, so live
    ("Tell me about Hurricane Beryl in Harris County", False, False),
])
def test_is_live_question(live_data, q, strict, expected):
    assert live_adk.is_live_question(q, strict=strict) is expected


def test_landing_router_sends_current_storm_questions_to_the_live_agent(live_data):
    agents = [{"id": "harris-hurricane", "county": "Harris County", "state": "TX", "hazard": "hurricane", "replay": "Beryl", "status": "live"}]
    assert landing_router.route("Which counties are at risk from Isaias?", agents) == {"kind": "agent", "agent_id": "live-storms"}
    assert landing_router.route("Tell me about Hurricane Beryl in Harris County", agents)["agent_id"] == "harris-hurricane"


def test_counties_tool_keeps_ranges_and_binds_truck_total_to_staging(live_data):
    out = live_adk.LiveToolset().get_counties_at_risk("Isaias")
    c = out["counties"][0]
    assert c["customers_out"] == {**RNG(52718, 75953, 134725), "unit": "customers"}
    assert out["staging"]["county"] == "Leon County"
    assert out["staging"]["trucks_needed_total"]["unit"] == "trucks"
    assert "error" in live_adk.LiveToolset().run_tool("get_counties_at_risk", {"storm": "Nonexistent"})


@pytest.mark.parametrize("question, expect", [
    ("Which storms are active right now?", "Hurricane Isaias: 100 kt (115 mph)"),
    ("Which counties are at risk from Isaias and where should trucks be staged?", "52,718 to 134,725 (median 75,953)"),
    ("What hospitals and fire departments does Baldwin County have for Isaias?", "229 career and 567 volunteer"),
])
def test_mock_live_agent_answers_pass_the_trust_layer(live_data, question, expect):
    agent, ts = live_adk.build_live_agent("mock")
    r = live_adk.run_live_agent(question, [], agent, ts)
    assert r["status"] == "passed", r["checks"]
    assert expect in r["answer"]
    assert r["tool_calls"][0]["name"] == "get_live_storms"


def test_live_page_sends_replay_questions_to_the_county_replay_agent(live_data):
    from agent import registry
    agents = [{"id": "harris-hurricane", "county": "Harris County", "state": "TX", "hazard": "hurricane", "replay": "Beryl", "status": "live"}]
    calls = []
    with patch.object(registry, "list_agents", return_value=agents), \
         patch.object(registry, "get", side_effect=lambda aid, *a: calls.append(aid) or ("hurricane", None, None)), \
         patch("agent.hurricane_adk.run_county_agent", return_value={"status": "passed", "answer": "replay"}):
        registry.chat("live-storms", "How bad was Hurricane Beryl in Harris County?", [])
        registry.chat("live-storms", "Where is Isaias headed?", [])  # names an active storm: stays live
    assert calls[0] == "harris-hurricane"
    assert calls[1] == "live-storms"
