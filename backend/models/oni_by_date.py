"""ONI anomaly for a specific date, adapted from xgboost-pred's county_context_features.py
(oni_anomaly_for_date). Reads the same oni/oni.ascii.txt file hurricane_tools.py's latest_oni()
already reads, but looks up the season covering a given date instead of the file's last row --
"latest" is wrong for a historical replay (e.g. a 2022 storm should see 2022's ENSO state, not
whatever is latest when this server happens to run), and the new model bundle was trained with
oni_anomaly varying per storm, so getting the date right matters for using it correctly.

Only the lookup-by-date is adapted here; county_context_features.py's NRI/SVI/MCC dataframe
lookups are not used -- this app already has each pack's real per-county population/customers/
NRI/SVI/tree-canopy cached in pack.json's profile (hurricane/build_pack.py), which is real
per-county data, unlike that module's own tree-canopy placeholder (see its TREE_CANOPY_PLACEHOLDER_PCT).
"""

from __future__ import annotations

from datetime import datetime

# Calendar order of NOAA's 12 rolling 3-month ONI seasons, DJF first -- matches
# build_training_table.py's SEASONS list exactly (month m's season is SEASONS[m - 1]).
SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]


def season_for_month(month: int) -> str:
    return SEASONS[month - 1]


def parse_oni_rows(text: str) -> list[tuple[str, int, float]]:
    """(season, year, anomaly) rows from oni.ascii.txt, same parsing as hurricane_tools.py's
    latest_oni()."""
    rows = []
    for line in text.splitlines():
        p = line.split()
        if len(p) == 4 and p[0] in SEASONS:
            rows.append((p[0], int(p[1]), float(p[3])))
    return rows


def oni_anomaly_for_date(oni_text: str, target_date: datetime) -> tuple[float | None, str, int]:
    """ONI anomaly for the season whose middle month is target_date's month, in target_date's
    year. Returns (anomaly_or_None, season, year) -- season/year are always returned, even on a
    miss, so callers can see what was searched for. None (never a substituted value) when that
    exact season/year isn't in the file -- e.g. a date in the future relative to NOAA's latest
    publication."""
    season, year = season_for_month(target_date.month), target_date.year
    for s, y, anom in parse_oni_rows(oni_text):
        if s == season and y == year:
            return anom, season, year
    return None, season, year
