"""Tests for Phase 3R: live NHC ATCF retrieval (CurrentStorms.json + aid_public
a-deck), storm selection, and handoff into run_impact_pipeline().

Fixture-based only -- no live internet dependency. Lines are modeled on the
same verified field order test_atcf_forecast.py and the real historical
archive use, plus a real excerpt structure confirmed against NHC's live
aid_public feed during this phase's manual integration check (see the
Phase 3R report for that separate, non-automated check).
"""

from __future__ import annotations

import gzip
import json

import pytest

from backend.models.live_atcf_source import (
    ActiveStormInfo,
    AtcfNetworkError,
    MalformedAtcfResponseError,
    NoActiveStormError,
    NoOfclForecastError,
    _adeck_url,
    fetch_current_adeck_bytes,
    fetch_current_storms_json,
    get_live_ofcl_forecast,
    parse_active_storms,
    parse_current_adeck,
    select_active_storm,
)
from backend.models.pipeline import MissingForecastDataError, run_impact_pipeline

# --- fixtures ------------------------------------------------------------------

CURRENT_STORMS_FIXTURE = json.dumps({
    "activeStorms": [
        {"id": "al052026", "basin": "AL", "name": "Helena", "classification": "HU"},
        {"id": "ep182026", "basin": "EP", "name": "Rachel", "classification": "HU"},
    ]
}).encode("utf-8")

EMPTY_STORMS_FIXTURE = json.dumps({"activeStorms": []}).encode("utf-8")


def _ofcl_line(tau: int, lat="250N", lon="800W", vmax="90") -> str:
    # Field layout verified against atcf_forecast.py's docstring and
    # test_atcf_forecast.py's LINE_WITH_RADII fixture: RAD1-4(13-16),
    # POUTER/ROUTER/RMW/GUSTS/EYE(17-21), SUBREGION(22, blank here),
    # MAXSEAS(23), INITIALS(24), DIR(25), SPEED(26), STORMNAME(27).
    return (
        f"AL, 05, 2026100412, 03, OFCL, {tau:3d}, {lat}, {lon}, {vmax:>3},    0, HU,  34, NEQ,"
        "  120,  120,   60,   60,    0,    0,    0,  65,    0,    ,    0, JLB, 350,   9, HELENA"
    )


def _carq_line() -> str:
    return (
        "AL, 05, 2026100412, 03, CARQ,   0, 250N,  800W,  90,    0, HU,  34, NEQ,"
        "    0,    0,    0,    0,    0,    0,    0,  65,    0,    ,    0, JLB, 350,   9, HELENA"
    )


OFCL_ADECK_TEXT = "\n".join([_ofcl_line(72), _ofcl_line(48), _ofcl_line(24), _carq_line()]) + "\n"
OFCL_ADECK_GZ = gzip.compress(OFCL_ADECK_TEXT.encode("utf-8"))

NO_OFCL_ADECK_GZ = gzip.compress((_carq_line() + "\n").encode("utf-8"))


# --- parse_active_storms / select_active_storm (pure, no network) -----------


def test_parse_active_storms_extracts_expected_fields():
    storms = parse_active_storms(CURRENT_STORMS_FIXTURE)
    assert storms == [
        ActiveStormInfo(atcf_id="AL052026", basin="AL", name="HELENA", classification="HU"),
        ActiveStormInfo(atcf_id="EP182026", basin="EP", name="RACHEL", classification="HU"),
    ]


def test_parse_active_storms_rejects_malformed_json():
    with pytest.raises(MalformedAtcfResponseError):
        parse_active_storms(b"not json at all {{{")


def test_parse_active_storms_rejects_missing_activestorms_field():
    with pytest.raises(MalformedAtcfResponseError):
        parse_active_storms(json.dumps({"somethingElse": []}).encode())


def test_select_active_storm_by_id():
    storms = parse_active_storms(CURRENT_STORMS_FIXTURE)
    storm = select_active_storm(storms, "AL052026", basin="AL")
    assert storm.name == "HELENA"


def test_select_active_storm_by_name_case_insensitive():
    storms = parse_active_storms(CURRENT_STORMS_FIXTURE)
    storm = select_active_storm(storms, "helena", basin="AL")
    assert storm.atcf_id == "AL052026"


def test_select_active_storm_basin_filter_excludes_other_basins():
    storms = parse_active_storms(CURRENT_STORMS_FIXTURE)
    # Rachel is EP182026 -- not in AL, so AL lookup must not find it even by name
    with pytest.raises(NoActiveStormError):
        select_active_storm(storms, "RACHEL", basin="AL")


def test_select_active_storm_raises_when_no_match():
    storms = parse_active_storms(CURRENT_STORMS_FIXTURE)
    with pytest.raises(NoActiveStormError, match="MILTON"):
        select_active_storm(storms, "MILTON", basin="AL")


def test_select_active_storm_raises_when_basin_has_no_active_storms():
    storms = parse_active_storms(EMPTY_STORMS_FIXTURE)
    with pytest.raises(NoActiveStormError, match="none"):
        select_active_storm(storms, "ANYTHING", basin="AL")


# --- parse_current_adeck (decompress + reuse atcf_forecast.load_atcf_forecasts) --


def test_parse_current_adeck_returns_ofcl_points_at_all_three_horizons():
    points = parse_current_adeck(OFCL_ADECK_GZ)
    taus = sorted(p.tau_h for p in points)
    assert taus == [24, 48, 72]
    assert all(p.tech == "OFCL" for p in points)


def test_parse_current_adeck_rejects_non_gzip_bytes():
    with pytest.raises(MalformedAtcfResponseError):
        parse_current_adeck(b"this is not gzip data")


def test_parse_current_adeck_rejects_empty_decompressed_content():
    with pytest.raises(MalformedAtcfResponseError):
        parse_current_adeck(gzip.compress(b""))


def test_parse_current_adeck_raises_when_no_ofcl_present():
    with pytest.raises(NoOfclForecastError):
        parse_current_adeck(NO_OFCL_ADECK_GZ)


# --- URL construction ----------------------------------------------------------


def test_adeck_url_matches_official_aid_public_pattern():
    assert _adeck_url("AL052026") == "https://ftp.nhc.noaa.gov/atcf/aid_public/aal052026.dat.gz"
    assert _adeck_url("EP182026") == "https://ftp.nhc.noaa.gov/atcf/aid_public/aep182026.dat.gz"


# --- network failure handling (monkeypatched urlopen, no real network) ------


def test_fetch_current_storms_json_wraps_network_error(monkeypatch):
    import urllib.request

    def boom(*args, **kwargs):
        raise OSError("DNS resolution failed")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(AtcfNetworkError):
        fetch_current_storms_json()


def test_fetch_current_adeck_bytes_wraps_network_error(monkeypatch):
    import urllib.request

    def boom(*args, **kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(AtcfNetworkError):
        fetch_current_adeck_bytes("AL052026")


# --- get_live_ofcl_forecast end-to-end (network layer monkeypatched) --------


def test_get_live_ofcl_forecast_end_to_end(monkeypatch):
    import backend.models.live_atcf_source as live_atcf_source

    monkeypatch.setattr(live_atcf_source, "fetch_current_storms_json", lambda timeout_s=15: CURRENT_STORMS_FIXTURE)
    monkeypatch.setattr(live_atcf_source, "fetch_current_adeck_bytes", lambda atcf_id, timeout_s=15: OFCL_ADECK_GZ)

    points, storm = get_live_ofcl_forecast("HELENA", basin="AL")
    assert storm.atcf_id == "AL052026"
    assert sorted(p.tau_h for p in points) == [24, 48, 72]


def test_get_live_ofcl_forecast_raises_no_active_storm(monkeypatch):
    import backend.models.live_atcf_source as live_atcf_source

    monkeypatch.setattr(live_atcf_source, "fetch_current_storms_json", lambda timeout_s=15: EMPTY_STORMS_FIXTURE)
    with pytest.raises(NoActiveStormError):
        get_live_ofcl_forecast("MILTON", basin="AL")


# --- handoff into run_impact_pipeline() --------------------------------------


def test_live_forecast_points_feed_select_live_snapshot_via_pipeline(monkeypatch):
    """The actual Phase 3R requirement: real retrieved+parsed ForecastPoints
    must be usable directly as run_impact_pipeline()'s forecast_points -- no
    adapter/shape mismatch. We don't need a full county/model mock here;
    MissingForecastDataError surfacing (rather than a TypeError/AttributeError
    from a shape mismatch) proves the handoff type-checks and reaches
    select_live_snapshot()'s own TAU-availability logic."""
    import backend.models.live_atcf_source as live_atcf_source

    monkeypatch.setattr(live_atcf_source, "fetch_current_storms_json", lambda timeout_s=15: CURRENT_STORMS_FIXTURE)
    monkeypatch.setattr(live_atcf_source, "fetch_current_adeck_bytes", lambda atcf_id, timeout_s=15: OFCL_ADECK_GZ)
    points, storm = live_atcf_source.get_live_ofcl_forecast("HELENA", basin="AL")

    # requesting a TAU this fixture's cycle does not have (96h) must raise the
    # existing, specific MissingForecastDataError -- not a generic crash
    with pytest.raises(MissingForecastDataError, match="tau_h"):
        run_impact_pipeline(county_fips=["12075"], forecast_points=points, lead_time_h=96)


# --- source/fallback metadata -------------------------------------------------


def test_predict_impact_tags_stub_fallback_data_source(monkeypatch):
    from backend.agent.tools import predict_impact
    monkeypatch.delenv("USE_ML_IMPACT_MODEL", raising=False)
    res = predict_impact(["12075"])
    assert res["data_source"] == "stub_fallback"


def test_predict_impact_falls_back_to_stub_when_live_storm_query_unset(monkeypatch):
    from backend.agent.tools import predict_impact
    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    monkeypatch.delenv("LIVE_STORM_QUERY", raising=False)
    res = predict_impact(["12075"])
    assert res["data_source"] == "stub_fallback"
    assert res["model_version"] == "stub-impact-v0"


def test_predict_impact_falls_back_to_stub_when_live_fetch_fails(monkeypatch):
    import backend.models.live_atcf_source as live_atcf_source
    from backend.agent.tools import predict_impact

    def boom(*args, **kwargs):
        raise AtcfNetworkError("simulated network outage")

    monkeypatch.setattr(live_atcf_source, "fetch_current_storms_json", boom)
    monkeypatch.setenv("USE_ML_IMPACT_MODEL", "true")
    monkeypatch.setenv("LIVE_STORM_QUERY", "HELENA")
    res = predict_impact(["12075"])
    assert res["data_source"] == "stub_fallback"
