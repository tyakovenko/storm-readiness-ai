"""Tests for Live NOAA/NHC and NWS Active Feed Ingestion Poller."""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.app import app
from backend.hurricane.live_feed import LiveFeedPoller, haversine_nm


@pytest.fixture
def client():
    return TestClient(app)


MOCK_NHC_PAYLOAD = {
    "activeStorms": [
        {
            "id": "al102026",
            "name": "LiveTestStorm",
            "classification": "HU",
            "intensity": "90",
            "pressure": "965",
            "latitudeNumeric": 29.5,
            "longitudeNumeric": -84.0,
            "movementDir": 35,
            "movementSpeed": 12,
            "lastUpdate": "2026-10-07T18:00:00.000Z",
            "publicAdvisory": {
                "advNum": "012",
                "url": "https://www.nhc.noaa.gov/text/test_adv.shtml",
            },
            "forecastAdvisory": {
                "url": "https://www.nhc.noaa.gov/text/test_fcst.shtml",
            },
        }
    ]
}

MOCK_NWS_PAYLOAD = {
    "features": [
        {
            "properties": {
                "id": "urn:oid:test-alert-1",
                "event": "Hurricane Warning",
                "severity": "Extreme",
                "urgency": "Immediate",
                "headline": "Hurricane Warning issued for Taylor County",
                "areaDesc": "Coastal Taylor; Inland Taylor",
                "geocode": {
                    "SAME": ["012123"],
                    "UGC": ["FLZ123"],
                },
                "effective": "2026-10-07T12:00:00Z",
                "expires": "2026-10-08T00:00:00Z",
            }
        },
        {
            "properties": {
                "id": "urn:oid:test-alert-2",
                "event": "Air Quality Alert",
                "severity": "Minor",
                "urgency": "Unknown",
                "headline": "Air quality advisory",
                "areaDesc": "Other County",
                "geocode": {"SAME": ["048113"], "UGC": ["TXZ113"]},
            }
        },
    ]
}


def test_haversine_nm_math():
    # Perry FL (30.1, -83.6) to Fort Myers FL (26.6, -81.9) is ~225-240 nm
    dist = haversine_nm(30.1, -83.6, 26.6, -81.9)
    assert 220.0 <= dist <= 250.0


def test_poller_parses_nhc_and_nws_data():
    poller = LiveFeedPoller(ttl_seconds=60.0)

    def mock_fetch(url, timeout=8.0):
        if "CurrentStorms" in url:
            return MOCK_NHC_PAYLOAD
        if "alerts/active" in url:
            return MOCK_NWS_PAYLOAD
        return None

    with patch("backend.hurricane.live_feed._fetch_url", side_effect=mock_fetch):
        status = poller.poll(force=True)
        assert status["status"] == "online"
        assert status["active_storms_count"] == 1
        assert status["active_tropical_alerts_count"] == 1

        storms = poller.get_active_storms()
        assert len(storms) == 1
        assert storms[0]["name"] == "Liveteststorm"
        assert storms[0]["intensity_kt"] == 90.0
        assert storms[0]["advisory_num"] == "012"

        alerts = poller.get_active_alerts()
        assert len(alerts) == 1
        assert alerts[0]["event"] == "Hurricane Warning"
        assert "12123" in alerts[0]["fips_codes"]


def test_poller_county_threat_evaluation():
    poller = LiveFeedPoller(ttl_seconds=60.0)

    def mock_fetch(url, timeout=8.0):
        if "CurrentStorms" in url:
            return MOCK_NHC_PAYLOAD
        if "alerts/active" in url:
            return MOCK_NWS_PAYLOAD
        return None

    with patch("backend.hurricane.live_feed._fetch_url", side_effect=mock_fetch):
        # Taylor County FL: ~30.0, -83.6. Storm is at 29.5, -84.0 (nearby)
        threat = poller.assess_county_threat(fips="12123", lat=30.0, lon=-83.6)
        assert threat["threat_level"] == "imminent"
        assert threat["closest_active_storm"] is not None
        assert threat["closest_active_storm"]["distance_nm"] < 100.0
        assert len(threat["county_active_alerts"]) == 1

        # Far away county: Dallas County TX (32.8, -96.8)
        threat_dallas = poller.assess_county_threat(fips="48113", lat=32.8, lon=-96.8)
        assert threat_dallas["threat_level"] == "none"
        assert len(threat_dallas["county_active_alerts"]) == 0


def test_poller_offline_resilience():
    poller = LiveFeedPoller(ttl_seconds=60.0)

    with patch("backend.hurricane.live_feed._fetch_url", return_value=None):
        status = poller.poll(force=True)
        assert status["status"] == "offline_or_fallback"
        assert status["active_storms_count"] == 0
        # Does not crash or raise exception
        storms = poller.get_active_storms()
        assert storms == []


def test_live_api_endpoints(client):
    def mock_fetch(url, timeout=8.0):
        if "CurrentStorms" in url:
            return MOCK_NHC_PAYLOAD
        if "alerts/active" in url:
            return MOCK_NWS_PAYLOAD
        return None

    with patch("backend.hurricane.live_feed._fetch_url", side_effect=mock_fetch):
        # Force refresh poller cache with mocked data
        from backend.hurricane.live_feed import get_poller
        get_poller().poll(force=True)

        # Test GET /api/live/status
        resp = client.get("/api/live/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "source" in data

        # Test GET /api/live/storms
        resp = client.get("/api/live/storms")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

        # Test GET /api/live/alerts
        resp = client.get("/api/live/alerts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

        # Test GET /api/live/threat/12123 (Taylor County)
        resp = client.get("/api/live/threat/12123")
        assert resp.status_code == 200
        threat = resp.json()
        assert threat["county_fips"] == "12123"
        assert "threat_level" in threat


def _ofcl(cycle_h, tau_h, lat, lon, vmax):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    cycle = datetime(2026, 10, 9, cycle_h, tzinfo=timezone.utc)
    return SimpleNamespace(cycle_init_time_utc=cycle, tau_h=tau_h, valid_time_utc=cycle + timedelta(hours=tau_h),
                           lat=lat, lon=lon, vmax_kt=vmax, mslp_mb=None)


def test_forecast_track_uses_latest_cycle_and_caches():
    points = [_ofcl(6, 0, 26.0, -88.0, 100), _ofcl(6, 12, 28.0, -87.5, 100),
              _ofcl(12, 12, 29.7, -86.8, 100), _ofcl(12, 0, 27.0, -87.6, 105)]
    poller = LiveFeedPoller()
    with patch("models.live_atcf_source.fetch_current_adeck_bytes", return_value=b"") as fetch, \
         patch("models.live_atcf_source.parse_current_adeck", return_value=points):
        track = poller.get_forecast_track("al092026")
        poller.get_forecast_track("AL092026")
    assert fetch.call_count == 1
    assert track["storm_id"] == "AL092026"
    assert track["cycle_utc"].startswith("2026-10-09T12:00")
    assert [(p["tau_h"], p["lat"]) for p in track["points"]] == [(0, 27.0), (12, 29.7)]


def test_forecast_track_endpoint_reports_unavailable(client):
    from models.live_atcf_source import AtcfNetworkError
    with patch("models.live_atcf_source.fetch_current_adeck_bytes", side_effect=AtcfNetworkError("offline")):
        resp = client.get("/api/live/storms/ZZ992026/track")
    assert resp.status_code == 503
