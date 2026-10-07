"""Candidate-county selection by distance (Phase 3G).

A thin filter on top of county_geometry.py's existing load_county_centroids()
(all ~3,200 US counties) and haversine_nm() -- no new distance math. Exists
because pipeline.py's 4-Florida-county table is a hardcoded stub specific to
that one scenario, not a reusable "which counties could this storm affect"
utility.
"""

from __future__ import annotations

import pandas as pd

from .county_geometry import haversine_nm

# Deliberately generous for a first real-data integration run (Phase 3G) --
# not a modeling decision. Override via max_distance_nm; narrow this once
# real feature/target coverage at various radii has been examined.
DEFAULT_CANDIDATE_RADIUS_NM = 300.0


def select_candidate_counties(
    centroids_df: pd.DataFrame,
    center_lat: float,
    center_lon: float,
    max_distance_nm: float = DEFAULT_CANDIDATE_RADIUS_NM,
) -> pd.DataFrame:
    """Counties within max_distance_nm of one point (e.g. a storm's landfall
    position), nearest first.

    Measures proximity to that ONE point, not the storm's full track -- the
    same documented limitation county_geometry.dist_to_track_nm() already
    carries for its single-snapshot distance. Returns centroids_df's columns
    plus a `dist_nm` column.
    """
    result = centroids_df.copy()
    result["dist_nm"] = result.apply(
        lambda row: haversine_nm(row["county_lat"], row["county_lon"], center_lat, center_lon),
        axis=1,
    )
    return result.loc[result["dist_nm"] <= max_distance_nm].sort_values("dist_nm").reset_index(drop=True)
