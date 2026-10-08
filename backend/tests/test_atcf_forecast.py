"""Tests for ATCF a-deck parsing and leakage-safe snapshot selection (Phase 3B).

Synthetic a-deck lines only -- no real archive data. Lines are modeled on
the verified field order (see atcf_forecast.py docstring) and on real
Hurricane Michael 2018 OFCL records inspected during field-position
verification.
"""

from datetime import datetime

import pytest

from backend.models.atcf_forecast import (
    ForecastSnapshot,
    filter_tech,
    group_forecast_points,
    load_atcf_forecasts,
    make_storm_id,
    parse_atcf_record,
    parse_latlon,
    select_leakage_safe_snapshot,
    select_snapshots_for_horizons,
)


# --- parse_latlon --------------------------------------------------------------


def test_parse_latlon_north_east():
    assert parse_latlon("178N") == pytest.approx(17.8)


def test_parse_latlon_south_west():
    assert parse_latlon("866W") == pytest.approx(-86.6)


def test_parse_latlon_rejects_unknown_hemisphere():
    with pytest.raises(ValueError):
        parse_latlon("178X")


def test_parse_latlon_rejects_empty():
    with pytest.raises(ValueError):
        parse_latlon("")


# --- parse_atcf_record ----------------------------------------------------------

LINE_WITH_RADII = (
    "AL, 14, 2018100618, 03, OFCL,  72, 260N,  875W,  55,    0, TS,  34, NEQ,"
    "  120,  120,   60,   60,    0,    0,    0,  65,    0,    ,    0, JLB, 350,   9, MICHAEL"
)
LINE_MISSING_DIR_SPEED = "AL, 14, 2018100618, 03, OFCL,   0, 178N,  866W,  25,    0, DB,  34, NEQ,    0,    0,    0,    0"
LINE_NON_OFCL = (
    "AL, 14, 2018100618, 03, CARQ,   0, 178N,  866W,  25,    0, DB,  34, NEQ,"
    "    0,    0,    0,    0,    0,    0,    0,  35,    0,    ,    0, JLB, 310,   5, "
)


def test_parse_atcf_record_basic_fields():
    rec = parse_atcf_record(LINE_WITH_RADII)
    assert rec.basin == "AL"
    assert rec.cyclone_num == 14
    assert rec.cycle_init_time_utc == datetime(2018, 10, 6, 18)
    assert rec.tech == "OFCL"
    assert rec.tau_h == 72
    assert rec.lat == pytest.approx(26.0)
    assert rec.lon == pytest.approx(-87.5)
    assert rec.vmax_kt == 55.0
    assert rec.storm_type == "TS"
    assert rec.storm_name == "MICHAEL"


def test_parse_atcf_record_wind_radii_fields():
    rec = parse_atcf_record(LINE_WITH_RADII)
    assert rec.rad_kt == 34
    assert rec.windcode == "NEQ"
    assert rec.radii_nm == (120.0, 120.0, 60.0, 60.0)


def test_parse_atcf_record_dir_speed_present():
    rec = parse_atcf_record(LINE_WITH_RADII)
    assert rec.dir_deg == 350.0
    assert rec.speed_kt == 9.0


def test_parse_atcf_record_missing_dir_speed_does_not_crash():
    rec = parse_atcf_record(LINE_MISSING_DIR_SPEED)
    assert rec.dir_deg is None
    assert rec.speed_kt is None
    assert rec.storm_name is None
    # core fields still parse correctly even with a short line
    assert rec.vmax_kt == 25.0
    assert rec.tau_h == 0


def test_parse_atcf_record_mslp_zero_is_treated_as_missing():
    rec = parse_atcf_record(LINE_WITH_RADII)
    assert rec.mslp_mb is None  # field value is "0", ATCF's "not reported" sentinel for MSLP


def test_parse_atcf_record_zero_radius_is_a_real_value_not_missing():
    # unlike MSLP, a 0 nm radius is a genuine "no wind of that speed" -- must not become None
    rec = parse_atcf_record(LINE_NON_OFCL)  # all four radii are "0" in this sample line
    assert rec.radii_nm == (0.0, 0.0, 0.0, 0.0)


# --- filter_tech -----------------------------------------------------------------


def test_filter_tech_keeps_only_ofcl():
    records = [parse_atcf_record(LINE_WITH_RADII), parse_atcf_record(LINE_NON_OFCL)]
    ofcl_only = filter_tech(records, "OFCL")
    assert len(ofcl_only) == 1
    assert ofcl_only[0].tech == "OFCL"


# --- make_storm_id ---------------------------------------------------------------


def test_make_storm_id():
    assert make_storm_id("AL", 14, datetime(2018, 10, 6)) == "AL142018"


# --- group_forecast_points: wind-radii merging -----------------------------------


def test_group_forecast_points_merges_multiple_rad_lines():
    line_34 = LINE_WITH_RADII
    line_50 = line_34.replace(" 34, NEQ,  120,  120,   60,   60", " 50, NEQ,   60,   60,    0,    0")
    records = [parse_atcf_record(line_34), parse_atcf_record(line_50)]
    points = group_forecast_points(records)
    assert len(points) == 1  # same cycle+TAU -> one merged ForecastPoint
    point = points[0]
    assert set(point.wind_radii.keys()) == {34, 50}
    assert point.wind_radii[34].ne_nm == 120.0
    assert point.wind_radii[50].ne_nm == 60.0
    assert point.vmax_kt == 55.0  # position/intensity fields carried over from either line


# --- building a multi-cycle synthetic forecast set for selection tests ----------


def _ofcl_line(init: str, tau: int, lat: str, lon: str, vmax: int) -> str:
    return (
        f"AL, 99, {init}, 03, OFCL, {tau:3d}, {lat}, {lon}, {vmax:3d},    0, HU,  34, NEQ,"
        "    0,    0,    0,    0,    0,    0,    0,  65,    0,    ,    0, JLB, 310,   9, TESTSTORM"
    )


def _build_multi_cycle_forecasts():
    """Four advisory cycles 6h apart, each forecasting the same impact time
    (2018-10-10 18Z) at a different TAU. Cycle D is issued AFTER the 24h
    snapshot moment and must never be selected for the 24h horizon."""
    lines = [
        _ofcl_line("2018100718", 72, "250N", "870W", 90),  # Cycle A: init = impact-72h
        _ofcl_line("2018100818", 48, "255N", "872W", 95),  # Cycle B: init = impact-48h
        _ofcl_line("2018100918", 24, "260N", "874W", 100),  # Cycle C: init = impact-24h
        _ofcl_line("2018101000", 18, "262N", "875W", 102),  # Cycle D: init = impact-18h (too late for 24h horizon)
    ]
    records = [parse_atcf_record(l) for l in lines]
    return group_forecast_points(filter_tech(records))


IMPACT_TIME = datetime(2018, 10, 10, 18)


def test_select_snapshot_72h_uses_earliest_cycle():
    points = _build_multi_cycle_forecasts()
    snap = select_leakage_safe_snapshot(points, IMPACT_TIME, 72)
    assert isinstance(snap, ForecastSnapshot)
    assert snap.cycle_init_time_utc == datetime(2018, 10, 7, 18)
    assert snap.forecast_tau_h == 72
    assert snap.valid_time_utc == IMPACT_TIME


def test_select_snapshot_48h_uses_cycle_b():
    points = _build_multi_cycle_forecasts()
    snap = select_leakage_safe_snapshot(points, IMPACT_TIME, 48)
    assert snap.cycle_init_time_utc == datetime(2018, 10, 8, 18)
    assert snap.forecast_tau_h == 48


def test_select_snapshot_24h_uses_cycle_c_not_cycle_d():
    points = _build_multi_cycle_forecasts()
    snap = select_leakage_safe_snapshot(points, IMPACT_TIME, 24)
    assert snap.cycle_init_time_utc == datetime(2018, 10, 9, 18)
    assert snap.forecast_tau_h == 24


def test_select_snapshot_never_uses_a_cycle_issued_after_snapshot_time():
    """Leakage guard: Cycle D (init 2018-10-10 00Z) is issued AFTER the 24h
    snapshot moment (2018-10-09 18Z) and must never be selected, even though
    its TAU=18 forecast lands exactly on impact_time."""
    points = _build_multi_cycle_forecasts()
    snap = select_leakage_safe_snapshot(points, IMPACT_TIME, 24)
    assert snap.cycle_init_time_utc != datetime(2018, 10, 10, 0)
    assert snap.forecast_tau_h != 18


def test_select_snapshot_returns_none_when_no_cycle_is_early_enough():
    points = _build_multi_cycle_forecasts()
    # 200h before impact is earlier than every available cycle
    snap = select_leakage_safe_snapshot(points, IMPACT_TIME, 200)
    assert snap is None


def test_select_snapshots_for_horizons_returns_all_three():
    points = _build_multi_cycle_forecasts()
    snapshots = select_snapshots_for_horizons(points, IMPACT_TIME, (72, 48, 24))
    assert set(snapshots.keys()) == {72, 48, 24}
    assert all(s is not None for s in snapshots.values())
    assert snapshots[72].forecast_tau_h == 72
    assert snapshots[48].forecast_tau_h == 48
    assert snapshots[24].forecast_tau_h == 24


# --- closest-TAU selection within a single eligible cycle ------------------------


def test_select_snapshot_picks_the_closest_tau_not_just_any_tau():
    """One cycle with two TAUs, neither landing exactly on impact_time:
    TAU=10 -> valid T0+10h (3h away), TAU=14 -> valid T0+14h (1h away).
    The closer one (14) must be picked."""
    t0 = "2018100700"
    lines = [
        _ofcl_line(t0, 10, "250N", "870W", 80),
        _ofcl_line(t0, 14, "251N", "871W", 85),
    ]
    points = group_forecast_points(filter_tech([parse_atcf_record(l) for l in lines]))
    impact = datetime(2018, 10, 7, 13)  # T0 + 13h
    snap = select_leakage_safe_snapshot(points, impact, lead_time_h=13)
    assert snap.forecast_tau_h == 14
    assert snap.lead_time_h == 13


# --- load_atcf_forecasts: end-to-end over a small synthetic file-like object -----


def test_load_atcf_forecasts_end_to_end(tmp_path):
    lines = [
        _ofcl_line("2018100718", 72, "250N", "870W", 90),
        LINE_NON_OFCL,  # should be filtered out (not OFCL)
    ]
    path = tmp_path / "sample.dat"
    path.write_text("\n".join(lines))
    points = load_atcf_forecasts(path)
    assert len(points) == 1
    assert points[0].tech == "OFCL"
    assert points[0].storm_id == "AL992018"
