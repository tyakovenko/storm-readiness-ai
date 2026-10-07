"""Tests for candidate-county selection by distance (Phase 3G).

Synthetic centroids only -- no real Census shapefile data.
"""

import pandas as pd
import pytest

from backend.models.county_geometry import haversine_nm
from backend.models.county_selection import DEFAULT_CANDIDATE_RADIUS_NM, select_candidate_counties

CENTER_LAT, CENTER_LON = 30.0, -85.5  # Michael's real landfall position

CENTROIDS = pd.DataFrame([
    {"county_fips": "12037", "county_lat": 30.05, "county_lon": -85.4},   # ~6nm away
    {"county_fips": "12077", "county_lat": 29.8, "county_lon": -85.0},    # ~45nm away
    {"county_fips": "13001", "county_lat": 32.0, "county_lon": -82.0},    # far away
])


def test_counties_within_threshold_are_included():
    result = select_candidate_counties(CENTROIDS, CENTER_LAT, CENTER_LON, max_distance_nm=100.0)
    assert set(result["county_fips"]) == {"12037", "12077"}


def test_counties_outside_threshold_are_excluded():
    result = select_candidate_counties(CENTROIDS, CENTER_LAT, CENTER_LON, max_distance_nm=100.0)
    assert "13001" not in set(result["county_fips"])


def test_dist_nm_column_matches_direct_haversine_call():
    result = select_candidate_counties(CENTROIDS, CENTER_LAT, CENTER_LON, max_distance_nm=1000.0)
    row = result.loc[result["county_fips"] == "12037"].iloc[0]
    expected = haversine_nm(30.05, -85.4, CENTER_LAT, CENTER_LON)
    assert row["dist_nm"] == pytest.approx(expected)


def test_result_sorted_nearest_first():
    result = select_candidate_counties(CENTROIDS, CENTER_LAT, CENTER_LON, max_distance_nm=1000.0)
    assert list(result["dist_nm"]) == sorted(result["dist_nm"])
    assert result.iloc[0]["county_fips"] == "12037"  # nearest


def test_empty_result_when_threshold_smaller_than_every_distance():
    result = select_candidate_counties(CENTROIDS, CENTER_LAT, CENTER_LON, max_distance_nm=1.0)
    assert len(result) == 0


def test_boundary_distance_is_inclusive():
    exact_dist = haversine_nm(30.05, -85.4, CENTER_LAT, CENTER_LON)
    result = select_candidate_counties(CENTROIDS, CENTER_LAT, CENTER_LON, max_distance_nm=exact_dist)
    assert "12037" in set(result["county_fips"])


def test_default_radius_used_when_not_specified():
    result_default = select_candidate_counties(CENTROIDS, CENTER_LAT, CENTER_LON)
    result_explicit = select_candidate_counties(
        CENTROIDS, CENTER_LAT, CENTER_LON, max_distance_nm=DEFAULT_CANDIDATE_RADIUS_NM
    )
    assert list(result_default["county_fips"]) == list(result_explicit["county_fips"])
