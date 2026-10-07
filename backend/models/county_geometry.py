"""County centroids and storm-to-county geometry.

Phase 3C of the real training-data ETL. Converts a Census county boundary
file into (county_fips, county_lat, county_lon), and a Phase 3B
ForecastSnapshot into per-county dist_to_track_nm / quadrant_right.

Does not estimate county wind, build the other 11 XGBoost features, or join
NRI/SVI/ONI/outage targets -- those are later phases.

County source: the Census 2025 1:500,000 cartographic boundary county file
(gs://uc3-storm-impact-intelligence-data/raw/census/counties/
cb_2025_us_county_500k.{shp,shx,dbf,prj}), cached locally the same way
dataset.py caches NRI/SVI (data/raw/..., gitignored). Its .prj confirms
NAD83 geographic coordinates (plain lat/lon degrees, no reprojection
needed), and its .dbf has a ready-to-use 5-char GEOID field.

Centroid choice: a plain vertex-averaged or area-weighted centroid can land
outside a county's land area entirely for concave or multi-part geometries
(barrier islands, inlets, a mainland + offshore-island county like several
in the Big Bend). We use Shapely's representative_point(), which is
guaranteed to fall inside the polygon, instead of .centroid.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import shapefile  # pyshp
from shapely.geometry import shape as shapely_shape

from .atcf_forecast import ForecastSnapshot
from .outage_target import normalize_fips

EARTH_RADIUS_NM = 3440.065  # mean Earth radius (6371.0088 km) in nautical miles


def load_county_centroids(shp_path: str | Path) -> pd.DataFrame:
    """Read a county boundary shapefile into one representative point per county.

    Returns columns: county_fips (normalized), county_lat, county_lon.
    Expects a GEOID attribute field (5-char FIPS) -- the Census cb_*_county
    cartographic boundary files all have one.
    """
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

    Used only by scenario_generator.py to dead-reckon a synthetic track's
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
    """Distance from one county to the snapshot's forecast storm position.

    This is the distance to that ONE selected point (the forecast valid at
    or nearest impact_time, per Phase 3B's leakage-safe selection) -- not
    the minimum distance to the whole forecast track. A storm that passes
    closer to this county earlier or later in the same forecast is not
    reflected here; that would require per-TAU minimum-distance logic,
    which is a different (and not yet decided) feature definition.
    """
    f = snapshot.forecast
    return haversine_nm(county_lat, county_lon, f.lat, f.lon)


def quadrant_right(county_lat: float, county_lon: float, snapshot: ForecastSnapshot) -> int | None:
    """1 if the county is in the storm's forward-right semicircle, 0 if
    forward-left, None if the forecast has no DIR (heading unknown).

    Northern-hemisphere hurricanes have their strongest winds on the
    right-front side of motion (rotation + translation add there), hence
    this specific binary split rather than plain north/south or left/right.

    Convention: relative_bearing = (bearing_to_county - heading) mod 360.
    Right semicircle = (0, 180) exclusive; dead-ahead (0) and dead-behind
    (180) both resolve to "not right" (0) -- an arbitrary but deterministic
    tie-break, since a point exactly on the track heading has no side.

    Returns None rather than guessing when DIR is missing -- callers decide
    the fallback (e.g. a schema default), this function does not invent one.
    """
    dir_deg = snapshot.forecast.dir_deg
    if dir_deg is None:
        return None

    f = snapshot.forecast
    bearing_to_county = bearing_deg(f.lat, f.lon, county_lat, county_lon)
    relative = (bearing_to_county - dir_deg) % 360
    return 1 if 0 < relative < 180 else 0
