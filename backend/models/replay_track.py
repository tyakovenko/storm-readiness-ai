"""Generalizes one pack's single-advisory replay.json into the full set of real ForecastPoints
across every tau_h that advisory published, for the storm-wide multi-county Risk Map.

hurricane/build_pack.py:replay() and models/replay_snapshot.py both already convert replay.json
into the xgboost-pred feature pipeline's ForecastPoint shape for ONE tau (the point nearest the
storm's actual closest approach to that county) -- what the existing per-county agent uses. This
module does the exact same real-data conversion (same bearing-based heading derivation between
real adjacent track points, same ForecastPoint shape) but keeps every tau_h the advisory
published, so the storm-wide view can offer genuinely different forecast horizons (e.g. 24h/48h/
72h after the advisory was issued) without fetching any new data or fabricating anything: it is
the same one real NHC advisory cycle already baked into the pack, just not collapsed to a single
point.

Horizon semantics (do not confuse with hurricane_tools.py's unrelated "lead_time_h", which means
hours from advisory issuance to the storm's closest approach to one county): a horizon here is
ATCF TAU -- hours from this one advisory's own issuance time, exactly what NHC's forecast
discussion means by "the 24-hour forecast position" etc. It is never a separate advisory cycle
and never hours-before-landfall.
"""

from __future__ import annotations

from datetime import datetime

from .atcf_forecast import ForecastPoint
from .county_geometry import bearing_deg

# Horizons this app offers in the UI, as hours after the advisory's own issuance (ATCF TAU).
# Only ever offered for a storm whose one real advisory actually published a point at that tau
# -- see available_horizons_h().
SUPPORTED_HORIZONS_H: tuple[int, ...] = (24, 48, 72)


def forecast_points_with_headings(replay: dict) -> list[ForecastPoint]:
    """Every real forecast point this pack's replay advisory published, as atcf_forecast.
    ForecastPoint objects with dir_deg filled in from the two real adjacent track points -- the
    same bearing calculation models/replay_snapshot.py already uses for its one point, just
    applied across the whole track so any tau can be selected, not only the point nearest
    closest approach. Never fabricates a point: only what replay["forecast"] already has."""
    storm_id = replay["storm_id"]
    storm_name = replay.get("storm_name")
    cycle_init = datetime.fromisoformat(replay["advisory_init_utc"])
    raw = sorted(replay["forecast"], key=lambda p: p["tau_h"])
    if not raw:
        raise ValueError("replay has no forecast points")

    points = []
    for i, p in enumerate(raw):
        neighbor = raw[i - 1] if i > 0 else (raw[i + 1] if i + 1 < len(raw) else None)
        dir_deg = None
        if neighbor is not None:
            earlier, later = (neighbor, p) if neighbor["tau_h"] < p["tau_h"] else (p, neighbor)
            dir_deg = bearing_deg(earlier["lat"], earlier["lon"], later["lat"], later["lon"])
        points.append(ForecastPoint(
            storm_id=storm_id, basin=storm_id[:2], cyclone_num=int(storm_id[2:4]), tech="OFCL",
            cycle_init_time_utc=cycle_init, tau_h=int(p["tau_h"]),
            valid_time_utc=datetime.fromisoformat(p["valid_utc"]),
            lat=float(p["lat"]), lon=float(p["lon"]), vmax_kt=float(p["vmax_kt"]),
            mslp_mb=None, storm_type="", dir_deg=dir_deg, speed_kt=None,
            storm_name=storm_name, wind_radii={},
        ))
    return points


def available_horizons_h(replay: dict) -> list[int]:
    """Of SUPPORTED_HORIZONS_H, which ones this pack's one real advisory actually published a
    point for -- the backend never offers (and never silently substitutes) a horizon it can't
    honor with a real forecast point."""
    taus = {int(p["tau_h"]) for p in replay["forecast"]}
    return [h for h in SUPPORTED_HORIZONS_H if h in taus]
