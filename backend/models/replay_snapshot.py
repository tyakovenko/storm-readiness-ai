"""Adapts this app's existing replay.json forecast track (lat/lon/vmax per tau_h -- no wind
radii, DIR or SPEED fields; see hurricane/build_pack.py:replay()) into the xgboost-pred feature
pipeline's ForecastSnapshot/ForecastPoint, so county_storm_features.compute_county_storm_features()
can run without re-fetching the raw ATCF a-deck archive (GCS-gated in this environment).

Because the baked replay has exactly one advisory cycle, this always yields exactly one snapshot
at that cycle's real lead time -- never a fabricated 24h/48h/72h selection. Getting genuinely
distinct snapshots at those horizons needs the raw multi-cycle a-deck (atcf_forecast.py's
select_snapshots_for_horizons), which this app cannot fetch without GCS credentials; see the
Phase 4 integration notes for why the horizon selector stays inert for these packs.

Honesty about what's real vs. derived:
 - lat/lon/vmax_kt: real (the replayed NHC forecast).
 - wind_radii: empty (not in replay.json) -- compute_county_storm_features() falls back to the
   same distance-decay formula used in training when no radius anchor exists for a point, which
   is a real path of the real pipeline, not a mismatch.
 - forward speed: left for compute_county_storm_features()'s OWN "derived from adjacent
   positions" fallback (resolve_forward_speed_kt) by supplying a real neighboring track point --
   never pre-computed here and mislabeled as the advisory's own SPEED field.
 - heading (dir_deg): derived here from the same two real adjacent positions, since
   county_geometry.quadrant_right() has no adjacent-point fallback of its own. If the replay
   track has only one point, dir_deg/quadrant_right and forward speed all come back None --
   county_storm_features' own missing-feature policy decides what happens next, not this module.
"""

from __future__ import annotations

from datetime import datetime

from .atcf_forecast import ForecastPoint, ForecastSnapshot
from .county_geometry import bearing_deg


def _point(storm_id: str, storm_name: str | None, cycle_init: datetime, p: dict, dir_deg: float | None) -> ForecastPoint:
    return ForecastPoint(
        storm_id=storm_id, basin=storm_id[:2], cyclone_num=int(storm_id[2:4]), tech="OFCL",
        cycle_init_time_utc=cycle_init, tau_h=int(p["tau_h"]), valid_time_utc=datetime.fromisoformat(p["valid_utc"]),
        lat=float(p["lat"]), lon=float(p["lon"]), vmax_kt=float(p["vmax_kt"]), mslp_mb=None, storm_type="",
        dir_deg=dir_deg, speed_kt=None, storm_name=storm_name, wind_radii={},
    )


def snapshot_from_replay(replay: dict) -> tuple[ForecastSnapshot, ForecastPoint | None]:
    """The one real advisory cycle this pack's replay.json carries, as a ForecastSnapshot, plus
    the real adjacent track point (if any) for compute_county_storm_features() to derive forward
    speed from. The snapshot's own forecast point is the one closest to the replay's recorded
    closest-approach time -- what get_storm_alert()/estimate_impact() already treat as "the"
    moment that matters for this county."""
    pts = sorted(replay["forecast"], key=lambda p: p["tau_h"])
    if not pts:
        raise ValueError("replay has no forecast points")
    cycle_init = datetime.fromisoformat(replay["advisory_init_utc"])
    storm_id, storm_name = replay["storm_id"], replay.get("storm_name")

    closest_utc = datetime.fromisoformat(replay["closest_approach_utc"])
    idx = min(range(len(pts)),
              key=lambda i: abs((datetime.fromisoformat(pts[i]["valid_utc"]) - closest_utc).total_seconds()))
    main_pt = pts[idx]
    neighbor_pt = pts[idx - 1] if idx > 0 else (pts[idx + 1] if idx + 1 < len(pts) else None)

    dir_deg = None
    if neighbor_pt is not None:
        earlier, later = (neighbor_pt, main_pt) if neighbor_pt["tau_h"] < main_pt["tau_h"] else (main_pt, neighbor_pt)
        dir_deg = bearing_deg(earlier["lat"], earlier["lon"], later["lat"], later["lon"])

    forecast_point = _point(storm_id, storm_name, cycle_init, main_pt, dir_deg)
    adjacent = _point(storm_id, storm_name, cycle_init, neighbor_pt, None) if neighbor_pt is not None else None

    snapshot = ForecastSnapshot(
        lead_time_h=float(replay["lead_time_h"]), forecast_tau_h=int(main_pt["tau_h"]),
        cycle_init_time_utc=cycle_init, valid_time_utc=forecast_point.valid_time_utc, forecast=forecast_point,
    )
    return snapshot, adjacent
