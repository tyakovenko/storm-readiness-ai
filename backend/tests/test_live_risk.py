"""Tests for the live storm -> at-risk counties / per-storm staging view (hurricane/live_risk.py)."""

from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from hurricane import live_risk
from hurricane.live_risk import _choose_staging, county_key


@pytest.mark.parametrize("raw, expected", [
    ("Baldwin County", "BALDWIN"),
    ("BALDWIN", "BALDWIN"),
    ("St. Tammany Parish", "ST TAMMANY"),
    ("SAINT TAMMANY", "ST TAMMANY"),
    ("Prince George's County", "PRINCE GEORGES"),
])
def test_county_key_matches_across_sources(raw, expected):
    assert county_key(raw) == expected


def _county(fips, lat, lon, out):
    return {"fips": fips, "lat": lat, "lon": lon, "customers_out": {"median": out}}


def test_staging_is_clear_of_track_big_enough_and_near_need():
    track = [(30.0, -87.0), (33.0, -87.0)]  # due-north track
    centroids = pd.DataFrame([
        {"county_fips": "A", "county_lat": 31.0, "county_lon": -87.2},   # on the track: excluded
        {"county_fips": "B", "county_lat": 31.0, "county_lon": -84.3},   # ~140 nm east, big: chosen
        {"county_fips": "C", "county_lat": 31.0, "county_lon": -84.0},   # clear, but too small
        {"county_fips": "D", "county_lat": 31.0, "county_lon": -82.0},   # clear and big, but farther
    ])
    customers = {"A": 500_000, "B": 200_000, "C": 10_000, "D": 900_000}
    names = {"B": {"name": "Bee County", "state": "AL"}}
    need = [_county("X", 31.0, -86.5, 50_000), _county("Y", 32.0, -86.8, 10_000)]

    st = _choose_staging(need, live_risk._densify(track), centroids, customers, names)

    assert st["fips"] == "B"
    assert st["clearance_from_track_nm"] >= live_risk.STAGING_CLEARANCE_NM
    assert st["name"] == "Bee County, AL staging area"


def test_no_staging_when_nothing_needs_trucks():
    assert _choose_staging([], [(30.0, -87.0)], pd.DataFrame(columns=["county_fips", "county_lat", "county_lon"]), {}, {}) is None


def test_risk_endpoint_404_for_inactive_storm():
    with patch.object(live_risk.get_poller(), "get_active_storms", return_value=[]):
        live_risk._cache.clear()
        resp = TestClient(app).get("/api/live/storms/ZZ992026/risk")
    assert resp.status_code == 404
