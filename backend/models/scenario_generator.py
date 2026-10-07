"""Deterministic synthetic hurricane scenario generator for the hackathon
demo, so the real inference pipeline can run (and produce real,
model-computed county predictions) even when there is no active Atlantic
storm to fetch from NHC.

Architecture (matches live_atcf_source.py's role exactly, just swapping the
network fetch for a synthetic generator):

    ScenarioConfig (explicit, centralized assumptions)
        -> generate_scenario_forecast_points()
        -> atcf_forecast.ForecastPoint / WindRadii objects (the SAME
           dataclasses real ATCF parsing produces -- nothing downstream can
           tell a scenario point from a real one by shape)
        -> pipeline.run_scenario_impact_pipeline() hands them to the
           EXISTING, UNMODIFIED run_impact_pipeline(): same feature
           engineering (county_storm_features.py / county_context_features.py),
           same trained outage_xgb_real_v1 model, same Phase 3P calibration.

This module NEVER computes an outage percentage, risk tier, uncertainty
range, or resource recommendation -- it only emits a hurricane FORECAST
INPUT. Every downstream number is a genuine output of the real pipeline.

Determinism: ScenarioConfig has no randomness and no wall-clock dependency
(cycle_init_time_utc is a fixed, explicit date -- chosen inside NOAA's
already-published JAS 2026 ONI season specifically so oni_anomaly always
resolves exactly, with no dependence on the Phase 3U "latest known ENSO
state" proxy or on when the demo happens to be run). The same config always
produces byte-identical ForecastPoints and therefore the same model output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .atcf_forecast import OFCL, ForecastPoint, WindRadii, make_storm_id
from .county_geometry import destination_point


@dataclass(frozen=True)
class ScenarioWindRadii:
    """Quadrant wind radii (nm) for one wind-speed threshold, NEQ convention
    (same as real ATCF records -- see atcf_forecast.py's WindRadii)."""

    ne_nm: float
    se_nm: float
    sw_nm: float
    nw_nm: float


@dataclass(frozen=True)
class ScenarioConfig:
    """Every assumption behind a synthetic scenario, centralized in one
    place -- change the storm here, nowhere else in the codebase. Track is a
    simple constant-heading, constant-speed dead-reckoning from
    (start_lat, start_lon) at cycle_init_time_utc (tau=0); intensity/wind
    radii are held constant across tau for MVP simplicity (no
    intensification/weakening model) -- an explicit, documented
    simplification, not a hidden one.
    """

    storm_name: str
    basin: str
    cyclone_num: int
    cycle_init_time_utc: datetime
    start_lat: float
    start_lon: float
    heading_deg: float  # constant track bearing, 0=N/90=E, degrees
    forward_speed_kt: float  # constant forward speed used to dead-reckon tau positions
    max_wind_kt: float  # VMAX, constant across tau
    mslp_mb: float
    storm_type: str
    wind_radii_kt: dict[int, ScenarioWindRadii]  # keyed by threshold, e.g. {34: ..., 50: ..., 64: ...}
    tau_values_h: tuple[int, ...] = (24, 48, 72)


# Florida Gulf Coast demo scenario. Track: starts in the central Gulf of
# Mexico (clearly open water, nowhere near Mexico/Cuba), heading NNE toward
# Florida's Big Bend -- the same region backend/agent/stub_data.py's demo
# advisory and DEFAULT_FIPS_TARGETS already use. At 7kt forward speed, this
# puts the storm ~120-140nm offshore at tau=24h (still approaching), making
# closest approach to the Big Bend counties (~40-85nm) at tau=48h, and well
# inland/moved on (~200-240nm away) by tau=72h -- a 3-day approach-landfall-
# inland arc, not a value chosen to hit a target outage number.
#
# max_wind_kt=90 (Category 2 equivalent) and the wind radii below are
# plausible real-world magnitudes for a storm that size (right-front/NE
# quadrant larger, matching the physical asymmetry county_storm_features.py
# already models for real storms) -- not tuned per-county.
FLORIDA_GULF_COAST_SCENARIO = ScenarioConfig(
    storm_name="ORION",
    basin="AL",
    cyclone_num=90,  # ATCF reserves 90-99 for test/non-operational storms each season; never a real cyclone number
    cycle_init_time_utc=datetime(2026, 8, 28, 6, 0, 0),
    start_lat=25.5,
    start_lon=-86.0,
    heading_deg=30.5,
    forward_speed_kt=7.0,
    max_wind_kt=90.0,
    mslp_mb=965.0,
    storm_type="HU",
    wind_radii_kt={
        64: ScenarioWindRadii(ne_nm=25, se_nm=20, sw_nm=15, nw_nm=15),
        50: ScenarioWindRadii(ne_nm=50, se_nm=40, sw_nm=35, nw_nm=35),
        34: ScenarioWindRadii(ne_nm=100, se_nm=90, sw_nm=80, nw_nm=80),
    },
)


def _track_position(config: ScenarioConfig, tau_h: int) -> tuple[float, float]:
    distance_nm = config.forward_speed_kt * tau_h
    return destination_point(config.start_lat, config.start_lon, config.heading_deg, distance_nm)


def generate_scenario_forecast_points(config: ScenarioConfig = FLORIDA_GULF_COAST_SCENARIO) -> list[ForecastPoint]:
    """Deterministic: the same config always produces byte-identical
    ForecastPoints. Reuses atcf_forecast.ForecastPoint/WindRadii exactly --
    this is the only output of this module; no wind/distance/outage/risk
    computation happens here.
    """
    storm_id = make_storm_id(config.basin, config.cyclone_num, config.cycle_init_time_utc)

    points = []
    for tau_h in config.tau_values_h:
        lat, lon = _track_position(config, tau_h)
        wind_radii = {
            threshold: WindRadii(windcode="NEQ", ne_nm=r.ne_nm, se_nm=r.se_nm, sw_nm=r.sw_nm, nw_nm=r.nw_nm)
            for threshold, r in config.wind_radii_kt.items()
        }
        points.append(ForecastPoint(
            storm_id=storm_id,
            basin=config.basin,
            cyclone_num=config.cyclone_num,
            tech=OFCL,
            cycle_init_time_utc=config.cycle_init_time_utc,
            tau_h=tau_h,
            valid_time_utc=config.cycle_init_time_utc + timedelta(hours=tau_h),
            lat=lat,
            lon=lon,
            vmax_kt=config.max_wind_kt,
            mslp_mb=config.mslp_mb,
            storm_type=config.storm_type,
            dir_deg=config.heading_deg,
            speed_kt=config.forward_speed_kt,
            storm_name=config.storm_name,
            wind_radii=wind_radii,
        ))
    return points
