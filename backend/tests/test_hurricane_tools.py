"""Unit tests for agent/hurricane_tools.py that need no published pack, GCS access, or model --
see test_hurricane_agent.py for the full-pack integration tests (skipped without real packs).
"""

import agent.hurricane_tools as ht
from agent.hurricane_tools import HurricaneToolset


def _toolset(monkeypatch, storms):
    """A bare HurricaneToolset (no __init__, so no pack/store access) with its I/O-bound helpers
    stubbed out, so find_similar_storms can be exercised on crafted storm records directly."""
    ts = HurricaneToolset.__new__(HurricaneToolset)
    ts.fips = "99999"
    ts.county = "Test County"
    monkeypatch.setattr(ts, "_storms", lambda: storms)
    monkeypatch.setattr(ts, "_forecast_features", lambda: {
        "max_wind_kt": 70.0, "dist_to_track_nm": 30.0, "forward_speed_kt": 12.0,
        "quadrant_right": True, "vmax_at_closest_kt": 75.0,
    })
    monkeypatch.setattr(ts, "_advisory_id", lambda: "TEST-ADVISORY")
    monkeypatch.setattr(ht, "latest_oni", lambda: {"oni_c": 0.5})
    return ts


def test_find_similar_storms_defaults_missing_oni_anomaly(monkeypatch):
    """Regression for the HTTP 500 on /api/agents/{id}/overview: the real Harris/Miami-Dade/Lee
    packs' storms.json entries have no "oni_anomaly" key at all. find_similar_storms used to
    drop the key from its output when absent, which failed PastStorm's required oni_anomaly
    field (pydantic ValidationError, uncaught up to a 500). It must now default to 0.0, exactly
    like the similarity calculation two lines above already does."""
    storms = [
        {"storm_id": "AL019999", "name": "NoOni 2024", "year": 2024, "max_wind_kt_at_county": 65.0,
         "dist_to_track_nm": 25.0, "right_of_track": True, "peak_customers_out": 1000,
         "peak_pct_customers": 10.0, "outage_data_coverage": "full"},
        {"storm_id": "AL029999", "name": "WithOni 2024", "year": 2024, "max_wind_kt_at_county": 60.0,
         "dist_to_track_nm": 40.0, "right_of_track": False, "peak_customers_out": 2000,
         "peak_pct_customers": 20.0, "outage_data_coverage": "full", "oni_anomaly": 1.2},
    ]
    ts = _toolset(monkeypatch, storms)

    out = ts.find_similar_storms()
    ht.CONTRACTS["find_similar_storms"].model_validate(out)  # raises on contract mismatch, same as run_tool

    assert "error" not in out
    by_id = {s["storm_id"]: s for s in out["storms"]}
    assert by_id["AL019999"]["oni_anomaly"] == 0.0
    assert by_id["AL029999"]["oni_anomaly"] == 1.2
