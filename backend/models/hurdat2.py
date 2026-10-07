"""HURDAT2 best-track parsing and landfall extraction.

HURDAT2 is NOAA's retrospective "best track" reanalysis -- real, ground-truth
positions/intensities, available only well after a storm has already
happened. This module exists solely to pick a storm's real impact_time_utc
(via its landfall record) for building the outage target window. Its output
must never be fed to the model as a predictive feature: during a real
forecast lead time this data does not exist yet, and doing so would leak the
future (see docs/data-contract.md's explicit HURDAT2-vs-advisory distinction).
This is a different format from atcf_forecast.py's a-deck FORECAST records --
do not confuse the two.

Format (verified against the real hurdat2_atlantic.txt, e.g. Hurricane
Michael 2018's AL142018 entry): a header line per storm
(`BASIN+CY+YEAR, NAME, N_TRACK_LINES,`) followed by exactly N comma-separated
track lines (`YYYYMMDD, HHMM, RECORD_ID, STATUS, LAT, LON, MAX_WIND,
MIN_PRESSURE, ...34/50/64kt quadrant wind radii..., RMW`). RECORD_ID is blank
for most rows and a single-letter flag otherwise; "L" means the storm's
center crossed a coastline at that observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Iterable

LANDFALL_RECORD_IDENTIFIER = "L"


def _parse_hurdat2_latlon(raw: str) -> float:
    """'30.0N' -> 30.0, '85.5W' -> -85.5 (trailing hemisphere letter)."""
    raw = raw.strip()
    hemi = raw[-1].upper()
    value = float(raw[:-1])
    return -value if hemi in ("S", "W") else value


@dataclass(frozen=True)
class Hurdat2TrackPoint:
    time: datetime
    record_identifier: str | None
    status: str
    lat: float
    lon: float
    max_wind_kt: float
    min_pressure_mb: float | None


@dataclass(frozen=True)
class Hurdat2Storm:
    storm_id: str
    name: str
    track: list[Hurdat2TrackPoint]


def _parse_track_line(line: str) -> Hurdat2TrackPoint:
    fields = [f.strip() for f in line.strip().split(",")]

    def get(i: int) -> str:
        return fields[i] if i < len(fields) else ""

    time = datetime.strptime(get(0) + get(1).zfill(4), "%Y%m%d%H%M")
    record_identifier = get(2) or None
    status = get(3)
    lat = _parse_hurdat2_latlon(get(4))
    lon = _parse_hurdat2_latlon(get(5))
    max_wind_kt = float(get(6))
    # HURDAT2 uses -999 for "not reported", never a real pressure, unlike
    # ATCF's a-deck format which uses 0 for the same purpose (see
    # atcf_forecast.py's parse_atcf_record) -- the two formats disagree here.
    pressure_raw = get(7)
    min_pressure_mb = float(pressure_raw) if pressure_raw and float(pressure_raw) > 0 else None

    return Hurdat2TrackPoint(
        time=time, record_identifier=record_identifier, status=status,
        lat=lat, lon=lon, max_wind_kt=max_wind_kt, min_pressure_mb=min_pressure_mb,
    )


def parse_hurdat2_storms(source: str | Path | IO) -> list[Hurdat2Storm]:
    """Parse a full HURDAT2 text file (path or file-like) into one
    Hurdat2Storm per header block. Each header declares exactly how many
    track lines follow it, so storms are delimited by that count, not by
    scanning for the next header line."""
    if hasattr(source, "readlines"):
        lines = source.readlines()
    else:
        with open(source, "r") as f:
            lines = f.readlines()

    storms = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        header_fields = [f.strip() for f in line.split(",")]
        storm_id, name, track_count = header_fields[0], header_fields[1], int(header_fields[2])

        track = []
        for _ in range(track_count):
            i += 1
            track.append(_parse_track_line(lines[i]))
        storms.append(Hurdat2Storm(storm_id=storm_id, name=name, track=track))
        i += 1

    return storms


def find_storm(storms: Iterable[Hurdat2Storm], storm_id: str) -> Hurdat2Storm:
    """Exact storm_id match (e.g. 'AL142018'). Raises -- never guesses a
    close match -- if the storm isn't present."""
    for storm in storms:
        if storm.storm_id == storm_id:
            return storm
    raise ValueError(f"No HURDAT2 storm found with id {storm_id!r}")


def landfall_record(storm: Hurdat2Storm) -> Hurdat2TrackPoint | None:
    """First track point flagged as a landfall (RECORD_IDENTIFIER == 'L').

    Returns None -- never a guess -- if the storm's track has no landfall
    flag at all (e.g. a storm that stayed entirely offshore); callers must
    treat that as a hard stop for this storm, not substitute another point.
    A storm with multiple real landfalls returns only the first one;
    disambiguating which landfall should anchor the outage window for such a
    storm is a documented limitation of this first integration run, not
    guessed here.
    """
    for point in storm.track:
        if point.record_identifier == LANDFALL_RECORD_IDENTIFIER:
            return point
    return None


# Continental US bounding box (lon_min, lon_max, lat_min, lat_max), used only
# to disambiguate storms with multiple real landfalls -- not a precision
# geographic boundary, just enough to separate "clearly not CONUS" records
# (Cuba, Mexico, the Caribbean) from "could be the US landfall we want" ones.
CONUS_BBOX = (-125.0, -66.0, 24.0, 50.0)


def select_us_landfall(storm: Hurdat2Storm) -> Hurdat2TrackPoint | None:
    """The storm's most significant CONUS landfall: among all landfall-
    flagged records whose position falls within CONUS_BBOX, the one with
    the highest max_wind_kt. Returns None if no landfall record falls within
    CONUS_BBOX at all (e.g. a storm that only hit Mexico/the Caribbean).

    Exists because landfall_record() intentionally returns only the FIRST
    'L' record (see its docstring). Several real Atlantic hurricanes make
    an earlier landfall elsewhere before their US landfall -- e.g. Ian's
    first 'L' is Cuba (2022-09-27, 110kt), its real Florida landfall is the
    3rd 'L' (2022-09-28 19:05, 130kt); Idalia's first 'L' is a 30kt tropical
    depression near the Yucatan, its Florida landfall is the 2nd (100kt).
    Picking by max wind among CONUS-filtered candidates resolves both
    correctly without per-storm special-casing. Scoped to US county-level
    training data; does not change landfall_record()'s existing behavior.
    """
    lon_min, lon_max, lat_min, lat_max = CONUS_BBOX
    candidates = [
        p for p in storm.track
        if p.record_identifier == LANDFALL_RECORD_IDENTIFIER
        and lon_min <= p.lon <= lon_max and lat_min <= p.lat <= lat_max
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.max_wind_kt)
