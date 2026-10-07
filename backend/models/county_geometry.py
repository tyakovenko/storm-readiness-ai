"""Storm-to-county geometry: pure-math functions, adapted from xgboost-pred's
backend/models/county_geometry.py.

Trimmed down from the source branch: that file's load_county_centroids() reads a Census
shapefile via pyshp/shapely to build a nationwide (fips -> lat/lon) table for a multi-county
training pipeline. This app already has each pack's own county centroid (hurricane/build_pack.py
-> pack.json's profile.centroid, from the same Census source), so the shapefile loader -- and the
two new dependencies it needs -- isn't pulled in here. Only the geometry math, which has no
dependency beyond the stdlib, is adapted.
"""

from __future__ import annotations

import math

from .atcf_forecast import ForecastSnapshot

EARTH_RADIUS_NM = 3440.065  # mean Earth radius (6371.0088 km) in nautical miles


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in nautical miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return EARTH_RADIUS_NM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing (0-360, 0=N, 90=E) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def dist_to_track_nm(county_lat: float, county_lon: float, snapshot: ForecastSnapshot) -> float:
    """Distance from one county to the snapshot's forecast storm position (the one selected
    point, not the minimum distance to the whole track)."""
    f = snapshot.forecast
    return haversine_nm(county_lat, county_lon, f.lat, f.lon)


def quadrant_right(county_lat: float, county_lon: float, snapshot: ForecastSnapshot) -> int | None:
    """1 if the county is in the storm's forward-right semicircle, 0 if forward-left, None if
    the forecast has no heading (dir_deg). Northern-hemisphere hurricanes have their strongest
    winds on the right-front side of motion (rotation + translation add there)."""
    dir_deg = snapshot.forecast.dir_deg
    if dir_deg is None:
        return None

    f = snapshot.forecast
    bearing_to_county = bearing_deg(f.lat, f.lon, county_lat, county_lon)
    relative = (bearing_to_county - dir_deg) % 360
    return 1 if 0 < relative < 180 else 0
