"""Tests for county centroids and storm-to-county geometry (Phase 3C).

Synthetic shapefiles and synthetic ForecastSnapshots only -- no real Census
or ATCF data.
"""

from datetime import datetime

import pytest
import shapefile

from backend.models.atcf_forecast import ForecastPoint, ForecastSnapshot
from backend.models.county_geometry import (
    bearing_deg,
    dist_to_track_nm,
    haversine_nm,
    load_county_centroids,
    quadrant_right,
)


def _make_snapshot(lat: float, lon: float, dir_deg: float | None) -> ForecastSnapshot:
    cycle = datetime(2018, 10, 7, 18)
    point = ForecastPoint(
        storm_id="AL992018",
        basin="AL",
        cyclone_num=99,
        tech="OFCL",
        cycle_init_time_utc=cycle,
        tau_h=72,
        valid_time_utc=cycle,
        lat=lat,
        lon=lon,
        vmax_kt=90.0,
        mslp_mb=950.0,
        storm_type="HU",
        dir_deg=dir_deg,
        speed_kt=10.0,
        storm_name="TESTSTORM",
        wind_radii={},
    )
    return ForecastSnapshot(
        lead_time_h=72, forecast_tau_h=72, cycle_init_time_utc=cycle, valid_time_utc=cycle, forecast=point
    )


# --- haversine_nm: known great-circle distances ---------------------------------


def test_haversine_nm_one_degree_longitude_at_equator_is_about_60nm():
    # 1 nautical mile was historically defined as 1 arc-minute of a great
    # circle, so 1 degree of longitude at the equator is ~60 nm.
    assert haversine_nm(0.0, 0.0, 0.0, 1.0) == pytest.approx(60.0, rel=1e-3)


def test_haversine_nm_one_degree_latitude_is_about_60nm():
    assert haversine_nm(0.0, 0.0, 1.0, 0.0) == pytest.approx(60.0, rel=1e-3)


def test_haversine_nm_same_point_is_zero():
    assert haversine_nm(28.0, -82.0, 28.0, -82.0) == pytest.approx(0.0, abs=1e-9)


def test_haversine_nm_is_symmetric():
    d1 = haversine_nm(25.0, -85.0, 29.0, -81.0)
    d2 = haversine_nm(29.0, -81.0, 25.0, -85.0)
    assert d1 == pytest.approx(d2)


# --- bearing_deg: longitude/latitude sign handling -------------------------------


def test_bearing_due_east_is_90():
    assert bearing_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0, abs=1e-6)


def test_bearing_due_north_is_0():
    assert bearing_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=1e-6)


def test_bearing_due_west_is_270():
    assert bearing_deg(0.0, 0.0, 0.0, -1.0) == pytest.approx(270.0, abs=1e-6)


def test_bearing_due_south_is_180():
    assert bearing_deg(0.0, 0.0, -1.0, 0.0) == pytest.approx(180.0, abs=1e-6)


# --- dist_to_track_nm: single selected forecast position, not track minimum -----


def test_dist_to_track_nm_uses_snapshot_forecast_position():
    snap = _make_snapshot(lat=28.0, lon=-82.0, dir_deg=0.0)
    d = dist_to_track_nm(28.0, -83.0, snap)
    assert d == pytest.approx(haversine_nm(28.0, -83.0, 28.0, -82.0))


def test_dist_to_track_nm_zero_when_county_at_storm_position():
    snap = _make_snapshot(lat=28.0, lon=-82.0, dir_deg=0.0)
    assert dist_to_track_nm(28.0, -82.0, snap) == pytest.approx(0.0, abs=1e-9)


# --- quadrant_right -----------------------------------------------------------


def test_quadrant_right_county_on_right_side():
    # storm moving due north (dir=0); county due east is on the right
    snap = _make_snapshot(lat=25.0, lon=-85.0, dir_deg=0.0)
    assert quadrant_right(25.0, -84.0, snap) == 1


def test_quadrant_right_county_on_left_side():
    # same storm, county due west is on the left
    snap = _make_snapshot(lat=25.0, lon=-85.0, dir_deg=0.0)
    assert quadrant_right(25.0, -86.0, snap) == 0


def test_quadrant_right_heading_wraparound_near_zero():
    # heading 350 deg (just west of due north); a county whose bearing from
    # the storm is 10 deg (just east of due north) is still on the right --
    # naive subtraction (10 - 350 = -340) must be wrapped mod 360 (= 20) to
    # get this right instead of a huge spurious angle.
    snap = _make_snapshot(lat=25.0, lon=-85.0, dir_deg=350.0)
    # place the county so bearing_from_storm ~= 10 degrees: slightly east and north
    county_lat, county_lon = 25.0 + 1.0 * 0.98, -85.0 + 1.0 * 0.17  # ~ bearing 10 deg
    assert bearing_deg(25.0, -85.0, county_lat, county_lon) == pytest.approx(10.0, abs=2.0)
    assert quadrant_right(county_lat, county_lon, snap) == 1


def test_quadrant_right_returns_none_when_dir_missing():
    snap = _make_snapshot(lat=25.0, lon=-85.0, dir_deg=None)
    assert quadrant_right(24.0, -84.0, snap) is None


# --- load_county_centroids: FIPS normalization + representative point ----------


def _write_sample_shapefile(base_path, counties):
    """counties: list of (geoid, [(lon, lat), ...]) closed rectangular rings."""
    with shapefile.Writer(str(base_path)) as w:
        w.field("GEOID", "C", size=5)
        w.field("NAME", "C", size=50)
        for geoid, ring in counties:
            w.poly([ring])
            w.record(GEOID=geoid, NAME=f"County {geoid}")


def test_load_county_centroids_normalizes_fips_and_stays_inside_polygon(tmp_path):
    rect_a = [(-82.5, 27.5), (-81.5, 27.5), (-81.5, 28.5), (-82.5, 28.5), (-82.5, 27.5)]
    rect_b = [(-90.0, 30.0), (-89.0, 30.0), (-89.0, 31.0), (-90.0, 31.0), (-90.0, 30.0)]
    base = tmp_path / "sample_counties"
    # GEOID "1029" is only 4 chars -- exercises normalize_fips zero-padding
    _write_sample_shapefile(base, [("12075", rect_a), ("1029", rect_b)])

    df = load_county_centroids(str(base) + ".shp")

    assert set(df["county_fips"]) == {"12075", "01029"}
    row_a = df.loc[df["county_fips"] == "12075"].iloc[0]
    assert 27.5 <= row_a["county_lat"] <= 28.5
    assert -82.5 <= row_a["county_lon"] <= -81.5


def test_load_county_centroids_missing_geoid_field_raises(tmp_path):
    base = tmp_path / "bad_shapefile"
    with shapefile.Writer(str(base)) as w:
        w.field("NAME", "C", size=50)
        w.poly([[(-82.5, 27.5), (-81.5, 27.5), (-81.5, 28.5), (-82.5, 28.5), (-82.5, 27.5)]])
        w.record(NAME="No FIPS County")
    with pytest.raises(ValueError, match="GEOID"):
        load_county_centroids(str(base) + ".shp")


# --- integration: real selection pipeline feeding the geometry functions --------


def test_integration_with_snapshot_from_select_leakage_safe_snapshot():
    from backend.models.atcf_forecast import (
        filter_tech,
        group_forecast_points,
        parse_atcf_record,
        select_leakage_safe_snapshot,
    )

    line = (
        "AL, 14, 2018100718, 03, OFCL,  72, 250N,  870W,  90,    0, HU,  34, NEQ,"
        "    0,    0,    0,    0,    0,    0,    0,  65,    0,    ,    0, JLB,   0,  10, MICHAEL"
    )
    points = group_forecast_points(filter_tech([parse_atcf_record(line)]))
    impact_time = datetime(2018, 10, 10, 18)
    snap = select_leakage_safe_snapshot(points, impact_time, lead_time_h=72)

    assert snap is not None
    # county due east of the forecast position, storm heading due north (dir=0)
    d = dist_to_track_nm(25.0, -86.0, snap)
    assert d > 0
    assert quadrant_right(25.0, -86.0, snap) == 1
