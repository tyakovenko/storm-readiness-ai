"""County centroids and storm-to-county geometry.

Provides pure-math distance/bearing calculations as well as county centroid
extraction from Census cartographic boundary shapefiles.

Functions:
- haversine_nm: Great-circle distance between two points in nautical miles.
- bearing_deg: Compass bearing (0-360 deg) between two points.
- destination_point: Dead-reckoning position given origin, bearing, and distance (used by scenario generator).
- dist_to_track_nm: Distance from a county representative point to an ATCF forecast position.
- quadrant_right: Identifies if a county is in the storm's forward-right semicircle.
- load_county_centroids: Reads Census county shapefiles into representative points using Shapely.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from .atcf_forecast import ForecastSnapshot
from .outage_target import normalize_fips

EARTH_RADIUS_NM = 3440.065  # mean Earth radius (6371.0088 km) in nautical miles


def load_county_centroids(shp_path: str | Path) -> pd.DataFrame:
    """Read a county boundary shapefile into one representative point per county.

    Returns columns: county_fips (normalized), county_lat, county_lon.
    Expects a GEOID attribute field (5-char FIPS) -- the Census cb_*_county
    cartographic boundary files all have one.
    """
    import shapefile  # pyshp
    from shapely.geometry import shape as shapely_shape

    with shapefile.Reader(str(shp_path)) as reader:
        field_names = [f[0] for f in reader.fields[1:]]  # skip the deletion-flag field
        if "GEOID" not in field_names:
            raise ValueError(f"Shapefile has no GEOID field; found {field_names}")

        rows = []
        for sr in reader.iterShapeRecords():
            geoid = sr.record["GEOID"]
            point = shapely_shape(sr.shape.__geo_interface__).representative_point()
            rows.append({"county_fips": normalize_fips(geoid), "county_lat": point.y, "county_lon": point.x})

    return pd.DataFrame(rows, columns=["county_fips", "county_lat", "county_lon"])


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


def destination_point(lat: float, lon: float, bearing_from_deg: float, distance_nm: float) -> tuple[float, float]:
    """Forward geodesic: the point reached travelling distance_nm from
    (lat, lon) along initial compass bearing_from_deg (0=N, 90=E). The
    inverse of bearing_deg()+haversine_nm() -- same great-circle model,
    same EARTH_RADIUS_NM, same bearing convention.

    Used by scenario_generator.py to dead-reckon a synthetic track's
    forecast positions; real ATCF-derived forecasts already carry their own
    parsed positions and never call this.
    """
    delta = distance_nm / EARTH_RADIUS_NM
    theta = math.radians(bearing_from_deg)
    phi1, lambda1 = math.radians(lat), math.radians(lon)

    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), (math.degrees(lambda2) + 540) % 360 - 180  # normalize lon to [-180, 180)


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
