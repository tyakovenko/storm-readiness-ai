"""Phase 3R: live NHC ATCF forecast retrieval.

Official NOAA/NHC sources:
  - Active-storm index:      https://www.nhc.noaa.gov/CurrentStorms.json
  - Current-season a-deck:   https://ftp.nhc.noaa.gov/atcf/aid_public/a{basin}{cyclone:02d}{year}.dat.gz

The aid_public a-deck is the SAME file format/convention as this project's
historical archive under data/raw/atcf/ -- NHC publishes the identical
a-deck tree for the current season, gzipped, updated every advisory cycle
while a storm is active. Parsing therefore reuses atcf_forecast.py's
existing, already-verified parser (load_atcf_forecasts -> parse_atcf_record
-> filter_tech -> group_forecast_points) completely unchanged: this module
only adds network retrieval and storm selection on top of it, never a
second ATCF parser.

Layering (each independently testable, see test_live_atcf_source.py):
  1. fetch_current_storms_json() / fetch_current_adeck_bytes() -- network I/O only
  2. parse_active_storms() / select_active_storm() -- pure, no network
  3. parse_current_adeck() -- decompress + reuse atcf_forecast.load_atcf_forecasts()
  4. get_live_ofcl_forecast() -- orchestrates 1-3 for one storm query

Semantic note (intentionally NOT solved in this phase): historical training
horizons (72h/48h/24h) were defined relative to the storm's ACTUAL HURDAT2
US landfall time, known only after the fact. A live, in-progress storm has
no such future ground truth. backend/models/pipeline.py's
select_live_snapshot() (Phase 3Q) instead uses the requested TAU from the
LATEST available advisory cycle -- so for live inference, "72h/48h/24h"
means forecast lead time from the current advisory cycle, not
hours-before-actual-landfall. The two are related but not the same
quantity; this module does not attempt to reconcile them.

MVP scope: Atlantic ("AL") basin only, per the project's current storm set.
CurrentStorms.json already carries other basins' storms (e.g. "EP") in the
same response at no extra retrieval cost, so basin is a filter parameter,
not a second code path -- but nothing here is wired to predict for a
non-Atlantic storm.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from .atcf_forecast import ForecastPoint, OFCL, load_atcf_forecasts

log = logging.getLogger(__name__)

CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
AID_PUBLIC_URL_TEMPLATE = "https://ftp.nhc.noaa.gov/atcf/aid_public/a{basin}{cyclone:02d}{year}.dat.gz"
DEFAULT_TIMEOUT_S = 15
ATLANTIC_BASIN = "AL"


class AtcfSourceError(RuntimeError):
    """Base class for live-ATCF-retrieval failures. Callers (pipeline/tools)
    decide whether/how to fall back -- never caught and papered over here."""


class AtcfNetworkError(AtcfSourceError):
    """A NOAA/NHC endpoint could not be reached, timed out, or returned a
    non-2xx status."""


class NoActiveStormError(AtcfSourceError):
    """No active storm matched the requested id/name in the requested basin
    (including: there are currently no active storms in that basin at all)."""


class MalformedAtcfResponseError(AtcfSourceError):
    """The response was not valid JSON (CurrentStorms.json) or not valid
    gzip/ATCF text (a-deck), or decompressed to zero records."""


class NoOfclForecastError(AtcfSourceError):
    """The a-deck parsed, but contained zero OFCL (official NHC forecast)
    points -- only guidance-model records are present. The trained model
    requires OFCL, the same technique the historical ETL used; a guidance
    model's intensity/track is not the quantity it was validated against."""


@dataclass(frozen=True)
class ActiveStormInfo:
    """One entry from NHC's CurrentStorms.json, trimmed to what this adapter
    needs to select a storm and build its a-deck URL."""

    atcf_id: str  # e.g. "AL052024"
    basin: str  # e.g. "AL"
    name: str  # e.g. "MILTON"
    classification: str  # NHC's own code, e.g. "HU", "TS"


def fetch_current_storms_json(timeout_s: int = DEFAULT_TIMEOUT_S) -> bytes:
    """Raw network fetch of NHC's active-storm index. Kept separate from
    parsing so tests can feed fixture bytes directly instead of hitting
    the network."""
    try:
        with urllib.request.urlopen(CURRENT_STORMS_URL, timeout=timeout_s) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AtcfNetworkError(f"Failed to reach {CURRENT_STORMS_URL}: {e}") from e


def parse_active_storms(raw_json: bytes) -> list[ActiveStormInfo]:
    """Pure parsing of CurrentStorms.json's activeStorms list -- no network.
    Raises MalformedAtcfResponseError on invalid JSON or an unexpected shape;
    tolerant of fields NHC doesn't always populate identically, but requires
    an `id` for every entry it keeps."""
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise MalformedAtcfResponseError(f"CurrentStorms.json response was not valid JSON: {e}") from e

    storms = payload.get("activeStorms")
    if storms is None:
        raise MalformedAtcfResponseError("CurrentStorms.json response has no 'activeStorms' field")

    out = []
    for s in storms:
        atcf_id = s.get("id") or s.get("atcfId") or s.get("atcf_id")
        if not atcf_id:
            continue
        out.append(ActiveStormInfo(
            atcf_id=atcf_id.upper(),
            basin=(s.get("basin") or atcf_id[:2]).upper(),
            name=(s.get("name") or "").upper(),
            classification=s.get("classification") or s.get("intensity") or "",
        ))
    return out


def select_active_storm(storms: list[ActiveStormInfo], query: str, basin: str = ATLANTIC_BASIN) -> ActiveStormInfo:
    """Find the requested storm by ATCF id ('AL052024') or name ('MILTON'),
    restricted to `basin` (MVP: Atlantic only). Raises NoActiveStormError
    naming exactly what was searched for and what else is active in that
    basin, rather than guessing or returning an arbitrary storm."""
    q = query.strip().upper()
    candidates = [s for s in storms if s.basin == basin.upper()]
    for s in candidates:
        if s.atcf_id == q or s.name == q:
            return s
    available = [f"{s.atcf_id}/{s.name}" for s in candidates]
    raise NoActiveStormError(
        f"No active {basin.upper()} storm matches {query!r}. "
        f"Active {basin.upper()} storms right now: {available or 'none'}"
    )


def _adeck_url(atcf_id: str) -> str:
    basin, cyclone, year = atcf_id[:2].lower(), int(atcf_id[2:4]), int(atcf_id[4:8])
    return AID_PUBLIC_URL_TEMPLATE.format(basin=basin, cyclone=cyclone, year=year)


def fetch_current_adeck_bytes(atcf_id: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> bytes:
    """Raw network fetch of one storm's current-season a-deck (gzipped).
    Kept separate from parsing so tests can feed fixture bytes directly."""
    url = _adeck_url(atcf_id)
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AtcfNetworkError(f"Failed to reach {url}: {e}") from e


def parse_current_adeck(gz_bytes: bytes, tech: str = OFCL) -> list[ForecastPoint]:
    """Decompress one storm's a-deck bytes and parse via
    atcf_forecast.load_atcf_forecasts() -- the SAME function the historical
    ETL uses, completely unchanged. Raises MalformedAtcfResponseError if the
    bytes aren't valid gzip/text or decompress to nothing, and
    NoOfclForecastError if parsing succeeds but no `tech` (default OFCL)
    points are present.
    """
    try:
        text = gzip.decompress(gz_bytes).decode("utf-8", errors="strict")
    except (gzip.BadGzipFile, OSError, UnicodeDecodeError) as e:
        raise MalformedAtcfResponseError(f"a-deck response was not valid gzip/text: {e}") from e

    if not text.strip():
        raise MalformedAtcfResponseError("a-deck response decompressed to zero records")

    points = load_atcf_forecasts(io.StringIO(text), tech=tech)
    if not points:
        raise NoOfclForecastError(
            f"a-deck decompressed to records but none were '{tech}' technique "
            "(official NHC forecast) -- only guidance-model records are present"
        )
    return points


def get_live_ofcl_forecast(
    storm_query: str,
    basin: str = ATLANTIC_BASIN,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> tuple[list[ForecastPoint], ActiveStormInfo]:
    """End-to-end live retrieval: find the active storm, fetch its current
    a-deck, parse its OFCL forecast points. This is the one function
    pipeline.py/tools.py call; steps above stay separately unit-testable.
    """
    raw_storms = fetch_current_storms_json(timeout_s)
    storms = parse_active_storms(raw_storms)
    storm = select_active_storm(storms, storm_query, basin)
    gz_bytes = fetch_current_adeck_bytes(storm.atcf_id, timeout_s)
    points = parse_current_adeck(gz_bytes, tech=OFCL)
    return points, storm
