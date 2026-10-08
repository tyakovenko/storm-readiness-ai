"""ATCF a-deck parsing and leakage-safe forecast-snapshot selection.

Phase 3B of the real training-data ETL (see docs/data-contract.md and the
project's ATCF field-position verification against the authoritative NRL
spec, science.nrlmry.navy.mil/atcf/docs/database/new/abdeck.txt).

This module only parses forecasts and picks which one represents "what was
known at T-minus-lead_time_h". It does not compute county distance, wind
exposure, or outage targets, and does not join any other dataset -- those
are later ETL phases.

Field order (0-indexed, verified against abdeck.txt and cross-checked
against real Hurricane Michael 2018 OFCL records):
  0 BASIN, 1 CY, 2 YYYYMMDDHH, 3 TECHNUM/MIN, 4 TECH, 5 TAU, 6 LatN/S,
  7 LonE/W, 8 VMAX, 9 MSLP, 10 TY, 11 RAD, 12 WINDCODE, 13-16 RAD1-4,
  17 POUTER, 18 ROUTER, 19 RMW, 20 GUSTS, 21 EYE, 22 SUBREGION,
  23 MAXSEAS, 24 INITIALS, 25 DIR, 26 SPEED, 27 STORMNAME.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Iterable

OFCL = "OFCL"
DEFAULT_LEAD_TIMES_H: tuple[float, ...] = (72, 48, 24)

# A single a-deck line only reports ONE wind-speed threshold's quadrant radii
# (RAD=34, 50, or 64). The same forecast point (same cycle/TAU) appears as
# multiple lines, one per threshold, with identical position/intensity/
# DIR/SPEED/name fields repeated on each -- only RAD/WINDCODE/RAD1-4 differ.
# Grouping those lines back into one ForecastPoint with a wind_radii dict is
# the main non-obvious parsing step here.


def parse_latlon(raw: str) -> float:
    """'178N' -> 17.8, '866W' -> -86.6 (tenths of a degree, trailing hemisphere letter)."""
    raw = raw.strip()
    if not raw:
        raise ValueError("empty lat/lon field")
    hemi = raw[-1].upper()
    digits = raw[:-1]
    value = float(digits) / 10.0
    if hemi in ("S", "W"):
        return -value
    if hemi in ("N", "E"):
        return value
    raise ValueError(f"unrecognized hemisphere letter in lat/lon {raw!r}")


@dataclass(frozen=True)
class WindRadii:
    windcode: str  # quadrant convention, e.g. "NEQ" = NE/SE/SW/NW
    ne_nm: float | None
    se_nm: float | None
    sw_nm: float | None
    nw_nm: float | None


@dataclass(frozen=True)
class RawAtcfRecord:
    """One a-deck line, before grouping multi-RAD lines into a ForecastPoint."""

    basin: str
    cyclone_num: int
    cycle_init_time_utc: datetime
    tech: str
    tau_h: int
    lat: float
    lon: float
    vmax_kt: float
    mslp_mb: float | None
    storm_type: str
    rad_kt: int | None
    windcode: str | None
    radii_nm: tuple[float | None, float | None, float | None, float | None]
    dir_deg: float | None
    speed_kt: float | None
    storm_name: str | None


def parse_atcf_record(line: str) -> RawAtcfRecord:
    """Parse one raw a-deck line. Trailing fields (DIR, SPEED, STORMNAME, ...)
    are optional in practice -- a short line must not crash the parser."""
    fields = [f.strip() for f in line.strip().split(",")]

    def get(i: int) -> str:
        return fields[i] if i < len(fields) else ""

    mslp_raw = get(9)
    # ATCF uses 0 as "not reported" for MSLP (never a real value for a tropical
    # system), unlike RAD1-4 where 0 genuinely means "no wind of that speed".
    mslp_mb = float(mslp_raw) if mslp_raw and float(mslp_raw) != 0 else None

    rad_raw = get(11)
    rad_kt = int(rad_raw) if rad_raw else None

    def radius(i: int) -> float | None:
        v = get(i)
        return float(v) if v != "" else None

    def opt_float(i: int) -> float | None:
        v = get(i)
        return float(v) if v != "" else None

    storm_name_raw = get(27)

    return RawAtcfRecord(
        basin=get(0),
        cyclone_num=int(get(1)),
        cycle_init_time_utc=datetime.strptime(get(2), "%Y%m%d%H"),
        tech=get(4),
        tau_h=int(get(5)),
        lat=parse_latlon(get(6)),
        lon=parse_latlon(get(7)),
        vmax_kt=float(get(8)),
        mslp_mb=mslp_mb,
        storm_type=get(10),
        rad_kt=rad_kt,
        windcode=get(12) or None,
        radii_nm=(radius(13), radius(14), radius(15), radius(16)),
        dir_deg=opt_float(25),
        speed_kt=opt_float(26),
        storm_name=storm_name_raw or None,
    )


def filter_tech(records: Iterable[RawAtcfRecord], tech: str = OFCL) -> list[RawAtcfRecord]:
    """Keep only one technique's records. Default OFCL = official NHC forecast,
    as opposed to CARQ/model-guidance/other aid techniques in the same file."""
    return [r for r in records if r.tech == tech]


@dataclass(frozen=True)
class ForecastPoint:
    """One official forecast: a storm's predicted position/intensity at a
    given TAU from a given advisory cycle, with wind radii merged across
    the 34/50/64kt lines for that same cycle+TAU."""

    storm_id: str
    basin: str
    cyclone_num: int
    tech: str
    cycle_init_time_utc: datetime
    tau_h: int
    valid_time_utc: datetime
    lat: float
    lon: float
    vmax_kt: float
    mslp_mb: float | None
    storm_type: str
    dir_deg: float | None
    speed_kt: float | None
    storm_name: str | None
    wind_radii: dict[int, WindRadii]


def make_storm_id(basin: str, cyclone_num: int, cycle_init_time_utc: datetime) -> str:
    """e.g. ('AL', 14, 2018-10-06...) -> 'AL142018'. Uses the cycle's own year;
    a storm cannot span two ATCF season years in practice (CY resets each season)."""
    return f"{basin}{cyclone_num:02d}{cycle_init_time_utc.year}"


def group_forecast_points(records: Iterable[RawAtcfRecord]) -> list[ForecastPoint]:
    """Merge same (basin, cyclone, cycle, tech, TAU) lines into one ForecastPoint."""
    groups: dict[tuple, list[RawAtcfRecord]] = {}
    for r in records:
        key = (r.basin, r.cyclone_num, r.cycle_init_time_utc, r.tech, r.tau_h)
        groups.setdefault(key, []).append(r)

    points = []
    for (basin, cyclone_num, cycle_init_time_utc, tech, tau_h), group in groups.items():
        first = group[0]
        wind_radii = {
            r.rad_kt: WindRadii(r.windcode, *r.radii_nm) for r in group if r.rad_kt is not None
        }
        points.append(
            ForecastPoint(
                storm_id=make_storm_id(basin, cyclone_num, cycle_init_time_utc),
                basin=basin,
                cyclone_num=cyclone_num,
                tech=tech,
                cycle_init_time_utc=cycle_init_time_utc,
                tau_h=tau_h,
                valid_time_utc=cycle_init_time_utc + timedelta(hours=tau_h),
                lat=first.lat,
                lon=first.lon,
                vmax_kt=first.vmax_kt,
                mslp_mb=first.mslp_mb,
                storm_type=first.storm_type,
                dir_deg=first.dir_deg,
                speed_kt=first.speed_kt,
                storm_name=first.storm_name,
                wind_radii=wind_radii,
            )
        )
    return sorted(points, key=lambda p: (p.cycle_init_time_utc, p.tau_h))


def _read_lines(source: str | Path | IO) -> list[str]:
    if hasattr(source, "readlines"):
        return source.readlines()
    with open(source, "r") as f:
        return f.readlines()


def load_atcf_forecasts(source: str | Path | IO, tech: str = OFCL) -> list[ForecastPoint]:
    """Parse an a-deck file (path or file-like) into grouped ForecastPoints
    for one technique (default OFCL)."""
    records = [parse_atcf_record(line) for line in _read_lines(source) if line.strip()]
    return group_forecast_points(filter_tech(records, tech))


@dataclass(frozen=True)
class ForecastSnapshot:
    """The forecast selected to represent "what was known at T-minus-lead_time_h"."""

    lead_time_h: float
    forecast_tau_h: int
    cycle_init_time_utc: datetime
    valid_time_utc: datetime
    forecast: ForecastPoint


def select_leakage_safe_snapshot(
    forecast_points: Iterable[ForecastPoint],
    impact_time_utc: datetime,
    lead_time_h: float,
) -> ForecastSnapshot | None:
    """Pick the forecast that represents the official outlook as of
    (impact_time_utc - lead_time_h), for the storm's eventual impact time.

    Leakage guard: a forecast cycle issued AFTER snapshot_time is never
    eligible, even if a later cycle's TAU would land closer to impact_time.
    Advisories are issued every ~6h, so the eligible cycle can be up to one
    cycle (~6h) earlier than lead_time_h implies -- this mirrors what an
    emergency manager actually had in hand at that moment, not a future
    forecast revised with information not yet available.
    """
    snapshot_time = impact_time_utc - timedelta(hours=lead_time_h)
    eligible = [p for p in forecast_points if p.cycle_init_time_utc <= snapshot_time]
    if not eligible:
        return None

    latest_cycle = max(p.cycle_init_time_utc for p in eligible)
    same_cycle = [p for p in eligible if p.cycle_init_time_utc == latest_cycle]
    best = min(same_cycle, key=lambda p: abs((p.valid_time_utc - impact_time_utc).total_seconds()))

    return ForecastSnapshot(
        lead_time_h=lead_time_h,
        forecast_tau_h=best.tau_h,
        cycle_init_time_utc=best.cycle_init_time_utc,
        valid_time_utc=best.valid_time_utc,
        forecast=best,
    )


def select_snapshots_for_horizons(
    forecast_points: Iterable[ForecastPoint],
    impact_time_utc: datetime,
    lead_times_h: Iterable[float] = DEFAULT_LEAD_TIMES_H,
) -> dict[float, ForecastSnapshot | None]:
    """Convenience wrapper: one leakage-safe snapshot per requested horizon."""
    points = list(forecast_points)
    return {h: select_leakage_safe_snapshot(points, impact_time_utc, h) for h in lead_times_h}
