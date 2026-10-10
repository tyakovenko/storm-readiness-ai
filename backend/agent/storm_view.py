"""Storm-wide, multi-county Risk Map data (Phase 1): one existing hurricane pack's own replayed
storm, extended to its real neighboring counties, at a real forecast horizon -- built entirely by
composing existing, unmodified modules (models/pipeline.run_impact_pipeline, the same trained
outage_xgb_real_v1 bundle and calibration the per-county agent uses) plus one new piece of
plumbing (models/replay_track.py) that turns a pack's baked replay.json into the ForecastPoint
shape that pipeline already expects. No model, calibration, or feature-engineering code is
duplicated or modified here.

This module is deliberately separate from agent/hurricane_tools.py: the per-county agent, its
tools and its trust-checked chat are untouched by Phase 1. This is a read-only dashboard
composition, like agent/registry.hurricane_overview() already is for the single-county screens.
"""

from __future__ import annotations

import logging

from hurricane import store
from hurricane.storm_regions import NEIGHBOR_FIPS
from models.pipeline import run_impact_pipeline
from models.replay_track import SUPPORTED_HORIZONS_H, available_horizons_h, forecast_points_with_headings

from .hurricane_contracts import CountyRiskSummary, StormShelterSummary, StormWideRiskView
from .hurricane_tools import _rng

log = logging.getLogger(__name__)


def _home_fips_for_slug(slug: str) -> str:
    match = next((p for p in store.index() if p.get("slug") == slug and p.get("hazard") == "hurricane"), None)
    if match is None:
        raise KeyError(slug)
    return match["fips"]


def _resolve_horizon(replay: dict, slug: str, horizon_h: int | None) -> tuple[int, list[int]]:
    """Shared horizon validation for build_storm_overview() and county_impact_at_horizon() --
    never silently rounds/substitutes a horizon this storm's one real advisory has no forecast
    point for."""
    available = available_horizons_h(replay)
    if not available:
        raise ValueError(f"storm {slug!r}: its advisory has none of the supported horizons {SUPPORTED_HORIZONS_H}")
    if horizon_h is None:
        return (48 if 48 in available else available[0]), available
    if horizon_h not in available:
        raise ValueError(f"horizon_h={horizon_h} not available for storm {slug!r}; this storm's one real "
                         f"advisory has forecast points at {available}")
    return horizon_h, available


def _is_published(fips: str) -> bool:
    """A county has a pack only if the index lists it. Checked first so a county without one
    doesn't cost an (uncached) failed bucket lookup on every overview request."""
    return any(p.get("fips") == fips for p in store.index())


def _shelters_for(fips: str) -> list[dict]:
    """Real shelters from that county's own pack, tagged with county_fips -- [] (never invented)
    for a county with no published pack."""
    if not _is_published(fips):
        return []
    try:
        shelters = store.table(fips, "assets.json").get("shelters", [])
    except store.PackUnavailable:
        return []
    return [
        {
            "id": s["id"], "name": s["name"], "county_fips": fips, "city": s.get("city"),
            "evacuation_capacity": s.get("evacuation_capacity"), "generator": bool(s.get("generator")),
            "pets": s.get("pets"), "in_surge_zone": bool(s.get("in_surge_zone")),
            "in_100yr_floodplain": bool(s.get("in_100yr_floodplain")), "lat": s.get("lat"), "lon": s.get("lon"),
        }
        for s in shelters
    ]


def _has_local_pack(fips: str) -> bool:
    if not _is_published(fips):
        return False
    try:
        store.table(fips, "assets.json")
    except store.PackUnavailable:
        return False
    return True


def build_storm_overview(slug: str, horizon_h: int | None = None) -> dict:
    """Raises KeyError for an unknown slug, ValueError for a horizon this storm's one real
    advisory has no forecast point for (never silently rounds/substitutes one)."""
    home_fips = _home_fips_for_slug(slug)
    pack = store.pack(home_fips)
    replay = store.table(home_fips, "replay.json")
    horizon_h, available = _resolve_horizon(replay, slug, horizon_h)

    points = forecast_points_with_headings(replay)
    targets = [home_fips] + [f for f in NEIGHBOR_FIPS.get(slug, []) if f != home_fips]

    result = run_impact_pipeline(
        county_fips=targets,
        advisory={"storm_id": replay["storm_id"], "storm_name": replay.get("storm_name"), "advisory_number": 0},
        forecast_points=points, lead_time_h=horizon_h,
    )

    counties = [
        CountyRiskSummary(
            fips=c["fips"], name=c["name"], state=c["state"], risk_tier=c["risk_tier"],
            pct_customers_out={**c["pct_customers_out"], "unit": "%"},
            customers_served=c["customers_served"], why=c["why"], has_local_pack=_has_local_pack(c["fips"]),
        )
        for c in result["counties"]
    ]
    shelters = [s for fips in targets for s in _shelters_for(fips)]

    view = StormWideRiskView(
        slug=slug, storm_id=replay["storm_id"], storm_name=f"{replay.get('storm_name')} {replay.get('year')}",
        kind="replay", home_county_fips=home_fips, advisory_init_utc=replay["advisory_init_utc"],
        horizon_h=horizon_h, available_horizons_h=available,
        counties=counties,
        shelters=[StormShelterSummary.model_validate(s) for s in shelters],
        model_version=result["model_version"], source=result["source"],
        caveat=(f"A real past NHC forecast for {replay.get('storm_name')} {replay.get('year')} (issued "
                f"{replay['advisory_init_utc'][:16].replace('T', ' ')} UTC), replayed for planning practice -- "
                "no live storm. Every county's prediction here is the same trained model used by "
                f"{pack['county']}'s own agent, at the forecast's +{horizon_h}h position from that advisory. "
                "Counties without a published readiness pack have a real prediction but no shelter or "
                "resource-planning data yet."),
    )
    return view.model_dump()


def county_impact_at_horizon(slug: str, horizon_h: int | None) -> dict:
    """The home county's own outage prediction at a specific forecast valid time (horizon_h hours
    after the advisory was issued) -- the same trained model/calibration and the same forecast
    track as build_storm_overview(), just for one county, shaped like
    HurricaneToolset.estimate_impact()'s return so the existing Storm Overview UI (ImpactPanel in
    frontend/src/hurricane/shared.jsx) can render it unmodified.

    This is deliberately a different number from estimate_impact()'s own closest-approach/peak
    snapshot (models/replay_snapshot.py): that tool answers "what's the worst this county should
    plan for" (fixed, not horizon-selectable); this answers "what does the model say at the
    specific valid time the Risk Map has selected" (Phase 2A: the two screens must agree when the
    same storm/county/horizon are selected, without conflating the two distinct questions)."""
    home_fips = _home_fips_for_slug(slug)
    replay = store.table(home_fips, "replay.json")
    horizon_h, _ = _resolve_horizon(replay, slug, horizon_h)

    points = forecast_points_with_headings(replay)
    result = run_impact_pipeline(
        county_fips=[home_fips],
        advisory={"storm_id": replay["storm_id"], "storm_name": replay.get("storm_name"), "advisory_number": 0},
        forecast_points=points, lead_time_h=horizon_h,
    )
    county = result["counties"][0]
    cust = county["customers_served"]
    q = county["pct_customers_out"]

    return {
        "county": county["name"], "fips": county["fips"], "risk_tier": county["risk_tier"],
        "pct_customers_out": _rng(q["low"], q["median"], q["high"], "%"),
        "customers_out": _rng(q["low"] * cust / 100, q["median"] * cust / 100, q["high"] * cust / 100,
                              "customers", 0),
        "customers_served": cust, "why": county["why"], "model_skill": {},
        "caveat": (f"Model prediction for this forecast's +{horizon_h}h valid time after the advisory was "
                   "issued -- not the peak/closest-approach estimate shown elsewhere on this page."),
        "source": result["source"], "model_version": result["model_version"], "engine": "pipeline_horizon",
        "calibration": {"severe_uncertainty_caveat": county.get("severe_uncertainty_caveat")},
        "horizon_h": horizon_h, "forecast_valid_time_utc": result["forecast_valid_time_utc"],
    }
