"""Tests for the dynamic county-level storm feature layer (Phase 3D).

Synthetic ForecastSnapshots only -- no real ATCF/Census data. Test storm is
centered at (25.0N, -85.0W), VMAX=100kt, heading due north (dir=0), with
NEQ quadrant radii: 64kt->30nm, 50kt->60nm, 34kt->120nm (clean round
numbers chosen so 1 degree of latitude ~= 60nm gives exact test distances).
"""

from datetime import datetime, timedelta

import pytest

from backend.models.atcf_forecast import ForecastPoint, ForecastSnapshot, WindRadii
from backend.models.county_storm_features import (
    compute_county_storm_features,
    estimate_county_wind_kt,
    resolve_forward_speed_kt,
)

STORM_LAT, STORM_LON = 25.0, -85.0
VMAX = 100.0
FULL_RADII = {
    64: WindRadii("NEQ", ne_nm=30.0, se_nm=30.0, sw_nm=25.0, nw_nm=25.0),
    50: WindRadii("NEQ", ne_nm=60.0, se_nm=60.0, sw_nm=50.0, nw_nm=50.0),
    34: WindRadii("NEQ", ne_nm=120.0, se_nm=120.0, sw_nm=100.0, nw_nm=100.0),
}


def _make_snapshot(
    *, dir_deg: float | None = 0.0, speed_kt: float | None = 10.0, wind_radii=None, vmax_kt=VMAX, tau_h=72
) -> ForecastSnapshot:
    cycle = datetime(2018, 10, 7, 18)
    point = ForecastPoint(
        storm_id="AL992018",
        basin="AL",
        cyclone_num=99,
        tech="OFCL",
        cycle_init_time_utc=cycle,
        tau_h=tau_h,
        valid_time_utc=cycle + timedelta(hours=tau_h),
        lat=STORM_LAT,
        lon=STORM_LON,
        vmax_kt=vmax_kt,
        mslp_mb=950.0,
        storm_type="HU",
        dir_deg=dir_deg,
        speed_kt=speed_kt,
        storm_name="TESTSTORM",
        wind_radii=wind_radii if wind_radii is not None else dict(FULL_RADII),
    )
    return ForecastSnapshot(
        lead_time_h=72, forecast_tau_h=tau_h, cycle_init_time_utc=cycle, valid_time_utc=point.valid_time_utc,
        forecast=point,
    )


def _county_due_north(distance_nm: float) -> tuple[float, float]:
    """Offset due north by distance_nm. 1 deg latitude ~= 60nm; bearing 0
    from the storm falls in the NE quadrant per county_storm_features'
    [0,90) convention, so this exercises the NE radii consistently."""
    return STORM_LAT + distance_nm / 60.0, STORM_LON


def _county_due_west(distance_nm: float) -> tuple[float, float]:
    """Bearing ~270 from the storm -> NW quadrant. Longitude degrees are not
    exactly 60nm (they shrink with cos(lat)), so this is approximate -- used
    only for the "different quadrant" test, not for exact-value assertions."""
    import math

    deg = distance_nm / (60.0 * math.cos(math.radians(STORM_LAT)))
    return STORM_LAT, STORM_LON - deg


# --- wind estimation: radius bands -----------------------------------------------


def test_wind_inside_64kt_radius():
    snap = _make_snapshot()
    lat, lon = _county_due_north(10.0)  # well inside the 30nm 64kt radius
    est = estimate_county_wind_kt(lat, lon, snap)
    assert est.method == "radius_interpolation"
    assert est.max_wind_kt >= 64.0
    # linear interpolation between (0, 100) and (30, 64): frac=10/30
    assert est.max_wind_kt == pytest.approx(100 + (10 / 30) * (64 - 100), abs=0.2)


def test_wind_between_64_and_50kt_radii():
    snap = _make_snapshot()
    lat, lon = _county_due_north(45.0)  # midpoint of 30nm and 60nm
    est = estimate_county_wind_kt(lat, lon, snap)
    assert est.method == "radius_interpolation"
    assert est.max_wind_kt == pytest.approx(57.0, abs=0.5)  # midpoint of 64 and 50
    assert 50.0 <= est.max_wind_kt <= 64.0


def test_wind_between_50_and_34kt_radii():
    snap = _make_snapshot()
    lat, lon = _county_due_north(90.0)  # midpoint of 60nm and 120nm
    est = estimate_county_wind_kt(lat, lon, snap)
    assert est.method == "radius_interpolation"
    assert est.max_wind_kt == pytest.approx(42.0, abs=0.5)  # midpoint of 50 and 34
    assert 34.0 <= est.max_wind_kt <= 50.0


def test_wind_outside_34kt_radius_uses_fallback():
    snap = _make_snapshot()
    lat, lon = _county_due_north(300.0)  # well beyond the 120nm 34kt radius
    est = estimate_county_wind_kt(lat, lon, snap)
    assert est.method == "vmax_decay_fallback"
    assert 0 < est.max_wind_kt <= VMAX


def test_wind_different_quadrant_uses_that_quadrants_radii():
    # NW radii (25/50/100nm) are tighter than NE (30/60/120nm) in this sample
    snap = _make_snapshot()
    lat, lon = _county_due_west(40.0)
    est = estimate_county_wind_kt(lat, lon, snap)
    # at 40nm: inside NW's 64kt radius (25) is false, between NW's 50kt (50) -> between 64kt and 50kt band
    assert est.method == "radius_interpolation"
    assert 50.0 <= est.max_wind_kt <= 64.0


# --- VMAX cap --------------------------------------------------------------------


def test_wind_at_storm_center_equals_vmax():
    snap = _make_snapshot()
    est = estimate_county_wind_kt(STORM_LAT, STORM_LON, snap)
    assert est.max_wind_kt == pytest.approx(VMAX)


def test_wind_never_exceeds_vmax_even_with_inconsistent_radii():
    # deliberately inconsistent data: VMAX=50 but a 64kt radius is still reported
    # (shouldn't happen in real data, but must not break the cap)
    bad_radii = {64: WindRadii("NEQ", ne_nm=30.0, se_nm=30.0, sw_nm=30.0, nw_nm=30.0)}
    snap = _make_snapshot(wind_radii=bad_radii, vmax_kt=50.0)
    lat, lon = _county_due_north(29.0)  # just inside the inconsistent 64kt radius
    est = estimate_county_wind_kt(lat, lon, snap)
    assert est.max_wind_kt <= 50.0


# --- missing/incomplete radii -----------------------------------------------------


def test_wind_no_radii_at_all_uses_fallback():
    snap = _make_snapshot(wind_radii={})
    lat, lon = _county_due_north(10.0)
    est = estimate_county_wind_kt(lat, lon, snap)
    assert est.method == "vmax_decay_fallback"


def test_wind_zero_radius_means_not_reached_not_missing():
    # a weak/disorganized system commonly reports 0 for every RAD1-4 field
    zero_radii = {34: WindRadii("NEQ", ne_nm=0.0, se_nm=0.0, sw_nm=0.0, nw_nm=0.0)}
    snap = _make_snapshot(wind_radii=zero_radii, vmax_kt=30.0)
    lat, lon = _county_due_north(10.0)
    est = estimate_county_wind_kt(lat, lon, snap)
    assert est.method == "vmax_decay_fallback"  # the 0 radius must not be used as an anchor


def test_wind_incomplete_radii_only_34kt_still_interpolates():
    only_34 = {34: WindRadii("NEQ", ne_nm=120.0, se_nm=120.0, sw_nm=100.0, nw_nm=100.0)}
    snap = _make_snapshot(wind_radii=only_34)
    lat, lon = _county_due_north(60.0)  # halfway to the 120nm 34kt radius
    est = estimate_county_wind_kt(lat, lon, snap)
    assert est.method == "radius_interpolation"
    assert est.max_wind_kt == pytest.approx(100 + 0.5 * (34 - 100), abs=0.5)


# --- gust ------------------------------------------------------------------------


def test_gust_is_1point25_times_max_wind():
    snap = _make_snapshot()
    features = compute_county_storm_features(STORM_LAT, STORM_LON, snap)
    assert features.gust_wind_kt == pytest.approx(features.max_wind_kt * 1.25, abs=0.01)


# --- forward speed -----------------------------------------------------------------


def test_forward_speed_uses_atcf_speed_field():
    snap = _make_snapshot(speed_kt=14.0)
    speed, source = resolve_forward_speed_kt(snap.forecast)
    assert speed == 14.0
    assert source == "atcf_speed_field"


def test_forward_speed_missing_without_adjacent_point_is_explicit():
    snap = _make_snapshot(speed_kt=None)
    speed, source = resolve_forward_speed_kt(snap.forecast)
    assert speed is None
    assert source == "missing"


def test_forward_speed_derived_from_adjacent_point():
    snap = _make_snapshot(speed_kt=None, tau_h=72)
    # a point 6h earlier, 60nm south (due-north offset reversed) -> implies ~10kt
    earlier = ForecastPoint(
        storm_id=snap.forecast.storm_id, basin="AL", cyclone_num=99, tech="OFCL",
        cycle_init_time_utc=snap.forecast.cycle_init_time_utc, tau_h=66,
        valid_time_utc=snap.forecast.valid_time_utc - timedelta(hours=6),
        lat=STORM_LAT - 1.0, lon=STORM_LON, vmax_kt=95.0, mslp_mb=955.0, storm_type="HU",
        dir_deg=0.0, speed_kt=None, storm_name="TESTSTORM", wind_radii={},
    )
    speed, source = resolve_forward_speed_kt(snap.forecast, adjacent_point=earlier)
    assert source == "derived_from_adjacent_positions"
    assert speed == pytest.approx(60.0 / 6.0, rel=0.02)  # ~60nm / 6h = 10kt


def test_forward_speed_missing_with_no_usable_adjacent_point_stays_missing():
    snap = _make_snapshot(speed_kt=None)
    same_time = ForecastPoint(
        storm_id=snap.forecast.storm_id, basin="AL", cyclone_num=99, tech="OFCL",
        cycle_init_time_utc=snap.forecast.cycle_init_time_utc, tau_h=snap.forecast.tau_h,
        valid_time_utc=snap.forecast.valid_time_utc,  # zero time delta -- can't derive a rate
        lat=STORM_LAT + 1.0, lon=STORM_LON, vmax_kt=95.0, mslp_mb=955.0, storm_type="HU",
        dir_deg=0.0, speed_kt=None, storm_name="TESTSTORM", wind_radii={},
    )
    speed, source = resolve_forward_speed_kt(snap.forecast, adjacent_point=same_time)
    assert speed is None
    assert source == "missing"


# --- quadrant_right passthrough (missingness preserved) ---------------------------


def test_quadrant_right_missing_dir_stays_none_in_full_feature_set():
    snap = _make_snapshot(dir_deg=None)
    features = compute_county_storm_features(*_county_due_north(50.0), snap)
    assert features.quadrant_right is None


# --- lead_time_h passthrough -------------------------------------------------------


def test_lead_time_h_comes_from_snapshot():
    snap = _make_snapshot()
    features = compute_county_storm_features(STORM_LAT, STORM_LON, snap)
    assert features.lead_time_h == 72


# --- integration: real ForecastSnapshot + county_geometry -------------------------


def test_integration_with_real_snapshot_and_county_geometry():
    from backend.models.atcf_forecast import (
        filter_tech,
        group_forecast_points,
        parse_atcf_record,
        select_leakage_safe_snapshot,
    )

    lines = [
        "AL, 14, 2018100718, 03, OFCL,  72, 250N,  870W, 100,    0, HU,  64, NEQ,"
        "   30,   30,   25,   25,    0,    0,    0,  65,    0,    ,    0, JLB,   0,  10, MICHAEL",
        "AL, 14, 2018100718, 03, OFCL,  72, 250N,  870W, 100,    0, HU,  50, NEQ,"
        "   60,   60,   50,   50,    0,    0,    0,  65,    0,    ,    0, JLB,   0,  10, MICHAEL",
        "AL, 14, 2018100718, 03, OFCL,  72, 250N,  870W, 100,    0, HU,  34, NEQ,"
        "  120,  120,  100,  100,    0,    0,    0,  65,    0,    ,    0, JLB,   0,  10, MICHAEL",
    ]
    points = group_forecast_points(filter_tech([parse_atcf_record(l) for l in lines]))
    impact_time = datetime(2018, 10, 10, 18)
    snap = select_leakage_safe_snapshot(points, impact_time, lead_time_h=72)
    assert snap is not None

    county_lat, county_lon = 25.1667, -87.0  # ~10nm due north of the forecast position
    features = compute_county_storm_features(county_lat, county_lon, snap)

    assert features.wind_estimate_method == "radius_interpolation"
    assert features.max_wind_kt >= 64.0
    assert features.gust_wind_kt == pytest.approx(features.max_wind_kt * 1.25, abs=0.01)
    assert features.dist_to_track_nm > 0
    assert features.forward_speed_kt == 10.0
    assert features.forward_speed_source == "atcf_speed_field"
    assert features.quadrant_right in (0, 1)
    assert features.lead_time_h == 72
