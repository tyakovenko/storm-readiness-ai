"""Tests for the response-team hurricane simulator (hurricane/simulator.py)."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from hurricane import simulator
from hurricane.live_feed import haversine_nm


def test_every_role_has_actions_for_every_phase():
    for role in simulator.ROLES:
        for phase in simulator.PHASES:
            assert simulator.PLAYBOOK[role][phase["key"]], (role, phase["key"])


def test_every_phase_has_one_right_decision_and_real_sources():
    for phase in simulator.PHASES:
        assert sum(correct for _, correct, _ in phase["decision"]["options"]) == 1, phase["key"]
        assert all(simulator.SRC[s]["url"].startswith("https://") for s in phase["sources"])


@pytest.mark.parametrize("approach", list(simulator.APPROACHES))
@pytest.mark.parametrize("offset, expected_nm", [("direct", 0), ("west", 40), ("east", 40)])
def test_synthetic_track_passes_the_county_at_the_chosen_distance_at_landfall(approach, offset, expected_nm):
    lat, lon = 25.6, -80.5  # Miami-Dade
    pts = simulator._synthetic_points(lat, lon, "4", approach, offset, 72)
    at_landfall = next(p for p in pts if p.tau_h == 72)
    assert haversine_nm(lat, lon, at_landfall.lat, at_landfall.lon) == pytest.approx(expected_nm, abs=1)
    assert all(p.vmax_kt == simulator.CATEGORIES["4"]["kt"] for p in pts)


def test_setup_lists_roles_and_storm_settings():
    s = TestClient(app).get("/api/simulate/setup").json()
    assert {r["id"] for r in s["roles"]} == set(simulator.ROLES)
    assert s["lead_times_h"] == [72, 48, 24]


def test_simulate_rejects_unknown_role_and_bad_settings():
    client = TestClient(app)
    assert client.post("/api/simulate", json={"role": "pilot", "fips": "12086"}).status_code == 404
    assert client.post("/api/simulate", json={"role": "fire", "fips": "12086", "hours_to_landfall": 5}).status_code in (404, 422)
