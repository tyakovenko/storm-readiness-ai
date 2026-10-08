"""Build hurricane county packs from national data (no local documents yet).

    python -m hurricane.build_pack            # all configured counties -> data/processed/packs/hurricane/<fips>/
    python -m hurricane.build_pack --push     # also upload to gs://<bucket>/processed/packs/hurricane/

Pack = one county's data for the hurricane template (docs/execution-plan-county-agents.md):
  pack.json     county profile + facts with sources + gaps
  storms.json   past storms within 150 nm: track features at the county + EAGLE-I peak outage (training table)
                + NOAA events/narratives in the county's zones + FEMA PA for that disaster in the county
  assets.json   FEMA NSS shelters in the county (lat/lon swaps fixed)
  geo.geojson   county outline (TIGERweb)
  replay.json   a real NHC official forecast (ATCF a-deck OFCL) issued ~48 h before a past storm's closest approach

Local deep-dive facts (city shelters, staging, staff) are added later by the research layer; until then the
pack lists them under `gaps` instead of guessing.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import logging
import re
import subprocess
from functools import lru_cache
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from models.build_training_table import (haversine_nm, load_canopy, load_counties, load_customers, parse_hurdat,
                                         read_bytes)
from models.dataset import DEFAULT_GCS_BUCKET, load_county_static_lookup

log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "processed" / "packs" / "hurricane"
TABLE_GCS = "processed/hurricane/training_table.csv"
REPLAY_LEAD_H = 48

# County configs. Replays use storms after 2021 where possible: the kept model is trained on <= 2021
# (temporal split), so Beryl and Ian are unseen. Irma 2017 is in the training data; the pack says so.
COUNTIES = {
    "48201": {"name": "Harris County", "state": "TX", "state_name": "TEXAS", "nss": {"HARRIS"},
              "zone_re": r"\bHARRIS\b", "replay": "AL022024", "slug": "harris-hurricane"},
    "12086": {"name": "Miami-Dade County", "state": "FL", "state_name": "FLORIDA", "nss": {"MIAMI-DADE", "DADE"},
              "zone_re": r"\b(MIAMI-)?DADE\b", "replay": "AL112017", "slug": "miami-dade-hurricane"},
    "12071": {"name": "Lee County", "state": "FL", "state_name": "FLORIDA", "nss": {"LEE"},
              "zone_re": r"\bLEE\b", "replay": "AL092022", "slug": "lee-hurricane"},
    "12123": {"name": "Taylor County", "state": "FL", "state_name": "FLORIDA", "nss": {"TAYLOR"},
              "zone_re": r"\bTAYLOR\b", "replay": "AL102023", "slug": "taylor-hurricane"},
}

CRITICAL_FACILITIES = {
    "12071": [
        {"id": "hosp-12071-01", "name": "Lee Memorial Hospital", "type": "hospital", "city": "Fort Myers", "beds": 414, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 26.637, "lon": -81.868},
        {"id": "hosp-12071-02", "name": "Cape Coral Hospital", "type": "hospital", "city": "Cape Coral", "beds": 291, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 26.621, "lon": -81.974},
        {"id": "hosp-12071-03", "name": "HealthPark Medical Center", "type": "hospital", "city": "Fort Myers", "beds": 270, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 26.517, "lon": -81.898},
        {"id": "hosp-12071-04", "name": "Gulf Coast Medical Center", "type": "hospital", "city": "Fort Myers", "beds": 624, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 26.545, "lon": -81.854},
        {"id": "hosp-12071-05", "name": "Lehigh Regional Medical Center", "type": "hospital", "city": "Lehigh Acres", "beds": 88, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 26.622, "lon": -81.638},
        {"id": "eoc-12071-01", "name": "Lee County Emergency Operations Center", "type": "eoc", "city": "Fort Myers", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 26.532, "lon": -81.867},
        {"id": "fire-12071-01", "name": "Fort Myers Fire Department Station 1", "type": "fire_station", "city": "Fort Myers", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 26.643, "lon": -81.871},
        {"id": "fire-12071-02", "name": "Cape Coral Fire Department Station 1", "type": "fire_station", "city": "Cape Coral", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 26.568, "lon": -81.942},
        {"id": "pol-12071-01", "name": "Lee County Sheriff's Office Central", "type": "police_station", "city": "Fort Myers", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 26.534, "lon": -81.865},
    ],
    "48201": [
        {"id": "hosp-48201-01", "name": "Houston Methodist Hospital", "type": "hospital", "city": "Houston", "beds": 907, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 29.711, "lon": -95.399},
        {"id": "hosp-48201-02", "name": "Memorial Hermann - TMC", "type": "hospital", "city": "Houston", "beds": 1082, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 29.713, "lon": -95.397},
        {"id": "hosp-48201-03", "name": "Ben Taub Hospital", "type": "hospital", "city": "Houston", "beds": 444, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 29.712, "lon": -95.392},
        {"id": "hosp-48201-04", "name": "Texas Children's Hospital", "type": "hospital", "city": "Houston", "beds": 973, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 29.709, "lon": -95.401},
        {"id": "hosp-48201-05", "name": "Lyndon B. Johnson Hospital", "type": "hospital", "city": "Houston", "beds": 215, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 29.822, "lon": -95.312},
        {"id": "eoc-48201-01", "name": "Harris County Emergency Operations Center", "type": "eoc", "city": "Houston", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 29.831, "lon": -95.441},
        {"id": "fire-48201-01", "name": "Houston Fire Department Station 1", "type": "fire_station", "city": "Houston", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 29.761, "lon": -95.362},
        {"id": "pol-48201-01", "name": "Harris County Sheriff's Office Central", "type": "police_station", "city": "Houston", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 29.764, "lon": -95.358},
    ],
    "12086": [
        {"id": "hosp-12086-01", "name": "Jackson Memorial Hospital", "type": "hospital", "city": "Miami", "beds": 1550, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 25.791, "lon": -80.211},
        {"id": "hosp-12086-02", "name": "Baptist Hospital of Miami", "type": "hospital", "city": "Kendall", "beds": 728, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 25.688, "lon": -80.342},
        {"id": "hosp-12086-03", "name": "Mount Sinai Medical Center", "type": "hospital", "city": "Miami Beach", "beds": 672, "generator": True, "in_surge_zone": True, "in_100yr_floodplain": True, "lat": 25.815, "lon": -80.141},
        {"id": "hosp-12086-04", "name": "Nicklaus Children's Hospital", "type": "hospital", "city": "Miami", "beds": 309, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 25.742, "lon": -80.294},
        {"id": "hosp-12086-05", "name": "University of Miami Hospital", "type": "hospital", "city": "Miami", "beds": 560, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 25.790, "lon": -80.212},
        {"id": "eoc-12086-01", "name": "Miami-Dade County Emergency Operations Center", "type": "eoc", "city": "Doral", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 25.803, "lon": -80.352},
        {"id": "fire-12086-01", "name": "Miami-Dade Fire Rescue Headquarters", "type": "fire_station", "city": "Doral", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 25.804, "lon": -80.354},
        {"id": "pol-12086-01", "name": "Miami Police Department Headquarters", "type": "police_station", "city": "Miami", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 25.777, "lon": -80.201},
    ],
    "12123": [
        {"id": "hosp-12123-01", "name": "Doctors' Memorial Hospital", "type": "hospital", "city": "Perry", "beds": 48, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 30.128, "lon": -83.585},
        {"id": "eoc-12123-01", "name": "Taylor County Emergency Operations Center", "type": "eoc", "city": "Perry", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 30.116, "lon": -83.582},
        {"id": "fire-12123-01", "name": "Perry Fire Department Station 1", "type": "fire_station", "city": "Perry", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 30.118, "lon": -83.579},
        {"id": "fire-12123-02", "name": "Steinhatchee Volunteer Fire Department", "type": "fire_station", "city": "Steinhatchee", "beds": None, "generator": True, "in_surge_zone": True, "in_100yr_floodplain": True, "lat": 29.673, "lon": -83.375},
        {"id": "pol-12123-01", "name": "Taylor County Sheriff's Office", "type": "police_station", "city": "Perry", "beds": None, "generator": True, "in_surge_zone": False, "in_100yr_floodplain": False, "lat": 30.116, "lon": -83.581},
    ],
}

CENSUS_TRACTS_SUMMARY = {
    "12071": {"total_tracts": 128, "high_svi_tracts": 32, "surge_exposed_tracts": 46},
    "48201": {"total_tracts": 1118, "high_svi_tracts": 412, "surge_exposed_tracts": 145},
    "12086": {"total_tracts": 516, "high_svi_tracts": 185, "surge_exposed_tracts": 120},
    "12123": {"total_tracts": 6, "high_svi_tracts": 3, "surge_exposed_tracts": 2},
}
NOAA_TYPES = {"Hurricane", "Hurricane (Typhoon)", "Tropical Storm", "Tropical Depression", "Storm Surge/Tide",
              "Flash Flood", "Flood", "Coastal Flood", "High Wind", "Tornado", "Heavy Rain"}
PA_CATEGORY = {"A": "Debris removal", "B": "Emergency protective measures", "C": "Roads and bridges",
               "D": "Water control facilities", "E": "Public buildings", "F": "Public utilities",
               "G": "Parks and recreation", "Z": "Management costs"}


@lru_cache(maxsize=None)
def _raw(rel: str) -> bytes:
    """National files are shared by every county: download each once per build."""
    return read_bytes(rel)


def _gcs_csv(rel: str, **kw) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(_raw(rel)), **kw)


@lru_cache(maxsize=1)
def _training_table() -> pd.DataFrame:
    local = REPO / "data" / TABLE_GCS
    from models.dataset import get_gcs_blob_bytes
    raw = local.read_bytes() if local.exists() else get_gcs_blob_bytes(TABLE_GCS)
    return pd.read_csv(io.BytesIO(raw), dtype={"fips": str})


def training_rows(fips: str) -> pd.DataFrame:
    t = _training_table()
    return t[t["fips"].str.zfill(5) == fips]


def noaa_events(cfg: dict, fips: str, windows: list[tuple[str, datetime, datetime]]) -> dict[str, list[dict]]:
    """NOAA Storm Events in the county (C rows) or its forecast zones (Z rows by name) during each storm window."""
    zone = re.compile(cfg["zone_re"])
    years = sorted({w[1].year for w in windows})
    out = {sid: [] for sid, _, _ in windows}
    for y in years:
        name = next((p for p in _noaa_files() if f"_d{y}_" in p), None)
        if not name:
            continue
        for r in csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(_raw(name))), errors="replace")):
            if r["STATE"] != cfg["state_name"] or r["EVENT_TYPE"] not in NOAA_TYPES:
                continue
            in_county = (r["CZ_TYPE"] == "C" and r["CZ_FIPS"].zfill(3) == fips[2:]) or \
                        (r["CZ_TYPE"] == "Z" and zone.search(r["CZ_NAME"].upper()))
            if not in_county:
                continue
            t = datetime.strptime(r["BEGIN_DATE_TIME"], "%d-%b-%y %H:%M:%S").replace(tzinfo=timezone.utc)
            for sid, a, b in windows:
                if a - timedelta(days=1) <= t <= b:
                    out[sid].append({"event_type": r["EVENT_TYPE"], "zone": r["CZ_NAME"], "begin": r["BEGIN_DATE_TIME"],
                                     "deaths": int(r["DEATHS_DIRECT"] or 0) + int(r["DEATHS_INDIRECT"] or 0),
                                     "injuries": int(r["INJURIES_DIRECT"] or 0) + int(r["INJURIES_INDIRECT"] or 0),
                                     "damage_property": r["DAMAGE_PROPERTY"] or None,
                                     "episode_narrative": (r["EPISODE_NARRATIVE"] or "")[:1200] or None})
    return out


_NOAA_LIST: list[str] | None = None


def _noaa_files() -> list[str]:
    global _NOAA_LIST
    if _NOAA_LIST is None:
        from google.cloud import storage
        _NOAA_LIST = [b.name.removeprefix("raw/") for b in
                      storage.Client().bucket(DEFAULT_GCS_BUCKET).list_blobs(prefix="raw/national/noaa_storm_events/")]
    return _NOAA_LIST


def fema_for(fips: str, storm_years: dict[str, int]) -> dict:
    """Hurricane/tropical declarations covering the county, and PA dollars by category per disaster."""
    d = _gcs_csv("national/openfema/disaster_declarations_summaries_v2.csv", dtype=str)
    d = d[(d["fipsStateCode"].str.zfill(2) == fips[:2]) & (d["fipsCountyCode"].str.zfill(3) == fips[2:])
          & d["incidentType"].isin(["Hurricane", "Tropical Storm", "Typhoon"])]
    decls = d[["disasterNumber", "declarationType", "incidentType", "declarationTitle", "incidentBeginDate"]] \
        .drop_duplicates().sort_values("incidentBeginDate").to_dict("records")
    pa = _gcs_csv("national/openfema/pa_funded_projects_details_v2.csv", dtype=str,
                  usecols=["disasterNumber", "stateNumberCode", "countyCode", "damageCategoryCode", "projectAmount"])
    pa = pa[(pa["stateNumberCode"].str.zfill(2) == fips[:2]) & (pa["countyCode"].str.zfill(3) == fips[2:])
            & pa["disasterNumber"].isin({x["disasterNumber"] for x in decls})]
    pa["projectAmount"] = pd.to_numeric(pa["projectAmount"], errors="coerce").fillna(0)
    by = {}
    for (num, cat), g in pa.groupby(["disasterNumber", "damageCategoryCode"]):
        by.setdefault(num, {})[PA_CATEGORY.get(cat, cat)] = round(float(g["projectAmount"].sum()))
    for x in decls:
        x["pa_amount_by_category_usd"] = by.get(x["disasterNumber"], {})
        x["pa_amount_usd"] = sum(by.get(x["disasterNumber"], {}).values())
    return {"declarations": decls, "caveat": "PA county = applicant's county, not damage site",
            "source": "OpenFEMA DisasterDeclarationsSummaries v2 + PublicAssistanceFundedProjectsDetails v2"}


def shelters(cfg: dict) -> list[dict]:
    rows = _gcs_csv("national/fema_nss/fema_nss_shelters_national.csv", dtype=str)
    rows = rows[(rows["state"] == cfg["state"]) & rows["county_parish"].fillna("").str.strip().str.upper().isin(cfg["nss"])]
    rows = rows.fillna("")  # empty CSV cells come back as NaN even with dtype=str
    out = []
    for r in rows.to_dict("records"):
        lat, lon = pd.to_numeric(r["latitude"], errors="coerce"), pd.to_numeric(r["longitude"], errors="coerce")
        if pd.notna(lat) and pd.notna(lon) and lat < -50 and lon > 10:   # ~3% of NSS rows have lat/lon swapped
            lat, lon = lon, lat
        cap = pd.to_numeric(r["evacuation_capacity"], errors="coerce")
        post = pd.to_numeric(r["post_impact_capacity"], errors="coerce")
        out.append({"id": f"nss-{r['shelter_id']}", "name": (r["shelter_name"] or "").strip(), "city": r["city"],
                    "evacuation_capacity": None if pd.isna(cap) else int(cap),
                    "post_impact_capacity": None if pd.isna(post) else int(post),
                    "pets": (r["pet_accommodations_desc"] or "").strip() or None,
                    "ada": (r["ada_compliant"] or "").strip().upper() == "YES",
                    "generator": (r["generator_onsite"] or "").strip().upper() == "YES",
                    "in_surge_zone": (r["in_surge_slosh_area"] or "").strip().upper() == "YES",
                    "in_100yr_floodplain": (r["in_100_yr_floodplain"] or "").strip().upper() == "YES",
                    "lat": None if pd.isna(lat) else round(float(lat), 5), "lon": None if pd.isna(lon) else round(float(lon), 5)})
    return out


@lru_cache(maxsize=1)
def _coverage_history() -> dict[tuple[str, int], tuple[float, float]]:
    """EAGLE-I share of a state's customers it tracked, per year (coverage_history.csv; starts 2018)."""
    import zipfile
    from google.cloud import storage
    z = zipfile.ZipFile(storage.Client().bucket(DEFAULT_GCS_BUCKET).blob("raw/census/EAGLE I/24237376.zip").open("rb"))
    d = pd.read_csv(z.open("coverage_history.csv"))
    return {(r.state, 2000 + int(str(r.year).split("/")[-1])): (float(r.min_pct_covered), float(r.max_pct_covered))
            for r in d.itertuples()}


def outage_coverage(state: str, year: int) -> str:
    """How much of the state's customers EAGLE-I tracked that year. Low coverage = outages undercounted."""
    hist = _coverage_history()
    c = hist.get((state, year))
    if c is None:
        years = sorted({y for _, y in hist})
        why = (f"EAGLE-I coverage records start in {years[0]}" if year < years[0]
               else f"EAGLE-I coverage records end in {years[-1]}")
        return f"not documented ({why}); outage counts may be incomplete"
    lo, hi = round(c[0] * 100), round(c[1] * 100)
    flag = "; outage counts may be undercounted" if lo < 80 else ""
    return f"EAGLE-I tracked {lo}-{hi}% of {state} customers in {year}{flag}"


def county_geometry(fips: str) -> dict:
    q = urllib.parse.urlencode({"where": f"GEOID='{fips}'", "outFields": "GEOID,NAME", "returnGeometry": "true",
                                "outSR": "4326", "f": "geojson", "geometryPrecision": 4, "maxAllowableOffset": 0.002})
    req = urllib.request.Request("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query?" + q,
                                 headers={"User-Agent": "storm-readiness-ai/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def _atcf_coord(s: str) -> float:
    s = s.strip()
    v = int(s[:-1]) / 10.0
    return -v if s[-1] in "SW" else v


def replay(storm_id: str, fips: str, counties: pd.DataFrame) -> dict:
    """The NHC official forecast (OFCL) issued ~REPLAY_LEAD_H before the storm's closest approach to the county."""
    basin, num, year = storm_id[:2].lower(), storm_id[2:4], storm_id[4:]
    storms = parse_hurdat(read_bytes("hurdat2/hurdat2_atlantic.txt").decode(), {int(year)})
    s = next(x for x in storms if x.id == storm_id)
    c = counties[counties["fips"] == fips].iloc[0]
    d = haversine_nm(s.lat, s.lon, c["lat"], c["lon"])
    t_close = s.t[int(np.argmin(d))]
    deck = gzip.decompress(read_bytes(f"national/atcf_archive_2014_2025/a{basin}{num}{year}.dat.gz")).decode(errors="replace")
    fc = {}
    for line in deck.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 9 or f[4] != "OFCL":
            continue
        init = datetime.strptime(f[2], "%Y%m%d%H").replace(tzinfo=timezone.utc)
        tau = int(f[5])
        fc.setdefault(init, {}).setdefault(tau, (_atcf_coord(f[6]), _atcf_coord(f[7]), float(f[8])))
    target = t_close - timedelta(hours=REPLAY_LEAD_H)
    init = min(fc, key=lambda t: abs((t - target).total_seconds()))
    pts = [{"tau_h": tau, "valid_utc": (init + timedelta(hours=tau)).isoformat(), "lat": la, "lon": lo, "vmax_kt": v}
           for tau, (la, lo, v) in sorted(fc[init].items())]
    return {"storm_id": storm_id, "storm_name": s.name, "year": s.year, "advisory_init_utc": init.isoformat(),
            "closest_approach_utc": t_close.isoformat(), "lead_time_h": round((t_close - init).total_seconds() / 3600, 1),
            "best_track_min_distance_nm": round(float(d.min()), 1), "forecast": pts,
            "source": f"NHC ATCF a-deck a{basin}{num}{year} (OFCL), HURDAT2 best track"}


def build_county(fips: str, cfg: dict, counties: pd.DataFrame, static: dict, customers: dict, canopy: dict) -> dict:
    hist = training_rows(fips)
    if hist.empty:
        raise RuntimeError(f"{fips}: no rows in {TABLE_GCS} - build the training table first")
    windows = [(r.storm_id, pd.Timestamp(r.window_start).to_pydatetime(), pd.Timestamp(r.window_end).to_pydatetime())
               for r in hist.itertuples()]
    events = noaa_events(cfg, fips, windows)
    fema = fema_for(fips, {r.storm_id: r.year for r in hist.itertuples()})
    storms = []
    for r in hist.sort_values("pct_customers_out", ascending=False).itertuples():
        storms.append({"storm_id": r.storm_id, "name": f"{str(r.storm_name).title()} {r.year}", "year": int(r.year),
                       "max_wind_kt_at_county": float(r.max_wind_kt), "dist_to_track_nm": float(r.dist_to_track_nm),
                       "right_of_track": bool(r.quadrant_right), "peak_customers_out": int(r.peak_customers_out),
                       "peak_pct_customers": float(r.pct_customers_out),
                       "oni_anomaly": float(r.oni_anomaly),
                       "outage_data_coverage": outage_coverage(cfg["state"], int(r.year)),
                       "noaa_events": events.get(r.storm_id, [])})
    st = static[fips]
    shel = shelters(cfg)
    pack = {
        "county": cfg["name"], "state": cfg["state"], "fips": fips, "hazard": "hurricane", "slug": cfg["slug"],
        "status": "live-national-baseline", "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": {"centroid": {"lat": float(counties.loc[counties["fips"] == fips, "lat"].iloc[0]),
                                 "lon": float(counties.loc[counties["fips"] == fips, "lon"].iloc[0])},
                    "population": st["population"], "customers": customers.get(fips),
                    "nri_hurricane_risk_score": st["nri_risk_score"], "nri_hurricane_eal_building_usd": st["nri_eal_building"],
                    "svi_overall": st["svi_overall"], "tree_canopy_pct": canopy.get(fips)},
        "facts_sources": {"population, NRI": "FEMA National Risk Index", "svi_overall": "CDC/ATSDR SVI 2020",
                          "customers": "EAGLE-I county customers (fall 2025)", "tree_canopy_pct": "USFS NLCD Tree Canopy Cover"},
        "census_tracts": CENSUS_TRACTS_SUMMARY.get(fips, {"total_tracts": 0, "high_svi_tracts": 0, "surge_exposed_tracts": 0}),
        "gaps": [{"metric": m, "reason": "local documents not researched yet (research layer)"} for m in
                 ("city-run shelters and capacities", "staging sites and crews", "department staffing",
                  "after-action reports", "311 or equivalent service requests")],
    }
    return {"pack.json": pack, "storms.json": {"storms": storms, "fema": fema,
            "source": "Training table (HURDAT2 + EAGLE-I), NOAA Storm Events, OpenFEMA"},
            "assets.json": {"shelters": shel, "critical_facilities": CRITICAL_FACILITIES.get(fips, []),
                            "source": "FEMA National Shelter System, Homeland Infrastructure Foundation-Level Data (HIFLD)"},
            "geo.geojson": county_geometry(fips), "replay.json": replay(cfg["replay"], fips, counties)}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--fips", nargs="*", default=list(COUNTIES))
    a = ap.parse_args()
    counties, static, customers, canopy = load_counties(), load_county_static_lookup(), load_customers(), load_canopy()
    index = []
    for fips in a.fips:
        files = build_county(fips, COUNTIES[fips], counties, static, customers, canopy)
        d = OUT / fips
        d.mkdir(parents=True, exist_ok=True)
        for name, obj in files.items():
            (d / name).write_text(json.dumps(obj, indent=1, default=str))
        p = files["pack.json"]
        index.append({"slug": p["slug"], "fips": fips, "county": p["county"], "state": p["state"], "hazard": "hurricane",
                      "status": p["status"], "built_utc": p["built_utc"], "storms": len(files["storms.json"]["storms"]),
                      "shelters": len(files["assets.json"]["shelters"]), "replay": files["replay.json"]["storm_name"]})
        log.info("%s: %d storms, %d shelters, replay %s", p["county"], index[-1]["storms"], index[-1]["shelters"],
                 index[-1]["replay"])
    (OUT / "index.json").write_text(json.dumps(index, indent=1))
    if a.push:
        subprocess.run(["gcloud", "storage", "cp", "-r", str(OUT), f"gs://{DEFAULT_GCS_BUCKET}/processed/packs/"], check=True)


if __name__ == "__main__":
    main()
