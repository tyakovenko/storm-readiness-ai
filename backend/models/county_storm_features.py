"""Dynamic, per-county storm features from a Phase 3B ForecastSnapshot.

Phase 3D of the real training-data ETL. Produces the 6 of the 13 XGBoost
features (backend/models/schema.py:FEATURE_COLUMNS) that depend on a
specific storm/forecast/county combination: max_wind_kt, gust_wind_kt,
dist_to_track_nm, forward_speed_kt, quadrant_right, lead_time_h. The other
7 (population_log, customers_served_log, tree_canopy_pct, nri_risk_score,
nri_eal_building_log, svi_overall, oni_anomaly) are static/county-level or
climate-level and are built elsewhere (not yet joined here).

This does NOT replace backend/models/pipeline.py's
estimate_county_wind_and_distance() yet -- that function is still what
agent/tools.py's predict_impact() calls today behind USE_ML_IMPACT_MODEL.
It uses a hardcoded 4-county distance table and a flat Vmax-decay formula
with no real track geometry. This module is the real-data replacement
candidate: once a later phase wires it into pipeline.py, that hardcoded
dist_map/decay function becomes dead code and should be deleted then --
not now, to avoid breaking the existing integration before the new path
is proven.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .atcf_forecast import ForecastPoint, ForecastSnapshot, WindRadii
from .county_geometry import bearing_deg, dist_to_track_nm, haversine_nm, quadrant_right

GUST_FACTOR = 1.25  # schema.py's existing, documented heuristic; no alternative found in-repo

WindEstimateMethod = Literal["radius_interpolation", "vmax_decay_fallback"]
ForwardSpeedSource = Literal["atcf_speed_field", "derived_from_adjacent_positions", "missing"]

# Fallback decay formula, carried over unchanged from pipeline.py's
# estimate_county_wind_and_distance() -- same shape, same constants. Used
# only when no usable wind-radius anchor exists (see estimate_county_wind_kt).
_FALLBACK_MIN_WIND_KT = 25.0
_FALLBACK_RMW_NM = 20.0
_FALLBACK_DECAY_SCALE_NM = 120.0


def _fallback_decay_wind_kt(vmax_kt: float, dist_nm: float) -> float:
    decay = max(0.2, min(1.0, 1.0 - (dist_nm - _FALLBACK_RMW_NM) / _FALLBACK_DECAY_SCALE_NM))
    return max(_FALLBACK_MIN_WIND_KT, vmax_kt * decay)


def _radius_for_quadrant(radii: WindRadii, bearing_from_storm_deg: float) -> float | None:
    """Pick the quadrant-specific radius (nm) for a bearing from the storm center.

    AAA windcode = one isotropic radius for all directions (stored in ne_nm).
    NEQ (the convention seen in every real OFCL record inspected so far) =
    four 90-degree quadrants, NE/SE/SW/NW in that order. Any other windcode
    is treated as NEQ too -- ATCF defines a couple of rarer conventions
    (e.g. quadrant pairs), but NEQ is what NHC's official forecast always
    uses in practice, so this is a documented simplification, not a blind
    guess.
    """
    if radii.windcode == "AAA":
        return radii.ne_nm
    b = bearing_from_storm_deg % 360
    if b < 90:
        return radii.ne_nm
    if b < 180:
        return radii.se_nm
    if b < 270:
        return radii.sw_nm
    return radii.nw_nm


@dataclass(frozen=True)
class CountyWindEstimate:
    max_wind_kt: float
    method: WindEstimateMethod


def estimate_county_wind_kt(
    county_lat: float, county_lon: float, snapshot: ForecastSnapshot
) -> CountyWindEstimate:
    """County-level sustained wind from VMAX + quadrant-specific 34/50/64kt radii.

    Method: build (distance_nm, wind_kt) anchor points --
      (0, VMAX) always, plus (radius, 64), (radius, 50), (radius, 34) for
      whichever thresholds have a real (nonzero) radius in the county's
      quadrant -- then linearly interpolate the county's distance between
      the two bracketing anchors. A radius of 0 means "storm's wind of that
      speed doesn't reach this quadrant at all" (a real, informative value,
      not missing data) and is excluded from the anchors, not treated as
      "64kt wind right at the center."

    This guarantees a county inside the 64kt radius gets >=64kt (it falls
    between the (0, VMAX) and (R64, 64) anchors, both >=64 by construction
    whenever VMAX>=64, which must hold if a 64kt radius is reported at
    all), and similarly for the 50/34kt bands.

    Fallback: if NO threshold has a usable (nonzero) radius in this
    quadrant -- common for weak/disorganized systems, which report 0 for
    every RAD1-4 field -- or the county is farther than every available
    radius, there is no track-geometry-based estimate to interpolate
    against. In that case the result comes from the same flat Vmax-decay
    formula pipeline.py already uses (distance-only, no quadrant
    awareness), and `method` is explicitly set to "vmax_decay_fallback" so
    callers can tell the two paths apart -- it is never blended invisibly
    into the radius-based estimate.

    The result is always capped at VMAX, regardless of which path produced
    it, since no point in a storm should be forecast as moving faster than
    the storm's own peak sustained wind.
    """
    forecast: ForecastPoint = snapshot.forecast
    dist_nm = dist_to_track_nm(county_lat, county_lon, snapshot)
    bearing_from_storm = bearing_deg(forecast.lat, forecast.lon, county_lat, county_lon)

    anchors: list[tuple[float, float]] = [(0.0, forecast.vmax_kt)]
    for threshold in (64, 50, 34):
        radii = forecast.wind_radii.get(threshold)
        if radii is None:
            continue
        radius_nm = _radius_for_quadrant(radii, bearing_from_storm)
        if radius_nm is not None and radius_nm > 0:
            anchors.append((radius_nm, float(threshold)))
    anchors.sort(key=lambda a: a[0])

    if len(anchors) == 1 or dist_nm > anchors[-1][0]:
        # no radius anchors at all, or county is beyond every known radius
        wind_kt = _fallback_decay_wind_kt(forecast.vmax_kt, dist_nm)
        method: WindEstimateMethod = "vmax_decay_fallback"
    else:
        lo, hi = anchors[0], anchors[-1]
        for a, b in zip(anchors, anchors[1:]):
            if a[0] <= dist_nm <= b[0]:
                lo, hi = a, b
                break
        if hi[0] == lo[0]:
            wind_kt = lo[1]
        else:
            frac = (dist_nm - lo[0]) / (hi[0] - lo[0])
            wind_kt = lo[1] + frac * (hi[1] - lo[1])
        method = "radius_interpolation"

    return CountyWindEstimate(max_wind_kt=round(min(wind_kt, forecast.vmax_kt), 1), method=method)


def resolve_forward_speed_kt(
    forecast: ForecastPoint, adjacent_point: ForecastPoint | None = None
) -> tuple[float | None, ForwardSpeedSource]:
    """ATCF's own SPEED field first; otherwise derive from one adjacent
    forecast point (same cycle, different TAU) if supplied; otherwise
    missing -- never silently falls back to schema.py's old 12kt default.
    """
    if forecast.speed_kt is not None:
        return forecast.speed_kt, "atcf_speed_field"

    if adjacent_point is not None:
        hours = abs((forecast.valid_time_utc - adjacent_point.valid_time_utc).total_seconds()) / 3600.0
        if hours > 0:
            dist_nm = haversine_nm(forecast.lat, forecast.lon, adjacent_point.lat, adjacent_point.lon)
            return dist_nm / hours, "derived_from_adjacent_positions"  # nm/h == kt

    return None, "missing"


@dataclass(frozen=True)
class CountyStormFeatures:
    max_wind_kt: float
    wind_estimate_method: WindEstimateMethod
    gust_wind_kt: float
    dist_to_track_nm: float
    forward_speed_kt: float | None
    forward_speed_source: ForwardSpeedSource
    quadrant_right: int | None
    lead_time_h: float


def compute_county_storm_features(
    county_lat: float,
    county_lon: float,
    snapshot: ForecastSnapshot,
    adjacent_point: ForecastPoint | None = None,
) -> CountyStormFeatures:
    """The 6 dynamic FEATURE_COLUMNS for one county at one forecast snapshot."""
    wind = estimate_county_wind_kt(county_lat, county_lon, snapshot)
    speed_kt, speed_source = resolve_forward_speed_kt(snapshot.forecast, adjacent_point)

    return CountyStormFeatures(
        max_wind_kt=wind.max_wind_kt,
        wind_estimate_method=wind.method,
        gust_wind_kt=round(wind.max_wind_kt * GUST_FACTOR, 1),
        dist_to_track_nm=dist_to_track_nm(county_lat, county_lon, snapshot),
        forward_speed_kt=speed_kt,
        forward_speed_source=speed_source,
        # quadrant_right already returns None on missing DIR; passed through unchanged.
        quadrant_right=quadrant_right(county_lat, county_lon, snapshot),
        lead_time_h=snapshot.lead_time_h,
    )
