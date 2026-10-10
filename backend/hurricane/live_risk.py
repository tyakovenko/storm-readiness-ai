"""Live storm -> at-risk US counties, their resources and storm history, and a per-storm staging site.

Composes existing pieces, no new model code:
  - the storm's official NHC forecast (live_feed poller -> live_atcf_source a-deck parser),
  - the same trained outage model + calibration every county agent uses (models.pipeline.run_impact_pipeline),
  - the national tables the pack builder already reads (FEMA NSS shelters, OpenFEMA declarations,
    the EAGLE-I training table of past storm outages),
plus two public national sources for the facilities the packs only carry for four counties:
  - CMS Hospital General Information (data.cms.gov provider-data API), by state, cached,
  - USFA National Fire Department Registry (apps.usfa.fema.gov/registry), downloaded once to data/raw.

Each county's prediction uses the forecast point closest to that county as its snapshot -- the
model was trained on the forecast valid at the storm's closest approach, so this is the matching
question. Nothing is invented: a county whose real feature data has a gap is reported as skipped.
"""

from __future__ import annotations

import io
import json
import logging
import math
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd

from models.dataset import LOCAL_DATA_DIR

from . import store
from .live_feed import USER_AGENT, get_poller, haversine_nm

log = logging.getLogger(__name__)

RISK_RADIUS_NM = 120.0          # county centroid within this of the forecast track while >= TS force
TS_FORCE_KT = 34.0
MAX_MODEL_COUNTIES = 40         # nearest candidates sent through the model
MAX_COUNTIES = 12               # highest predicted impact kept for display
STAGING_CLEARANCE_NM = RISK_RADIUS_NM + 10  # staging site stays outside the at-risk band of the whole track
STAGING_MIN_CUSTOMERS = 75_000  # a county big enough to host a staging yard
# ASSUMPTION (planning rule of thumb, not data): one utility truck per this many predicted customers out.
CUSTOMERS_OUT_PER_TRUCK = 2_000
CACHE_TTL_SEC = 900.0

USFA_URL = "https://apps.usfa.fema.gov/registry/api/download/national"
USFA_LOCAL = LOCAL_DATA_DIR / "raw" / "national" / "usfa" / "usfa_registry_national.csv"
CMS_HOSPITALS_URL = "https://data.cms.gov/provider-data/api/1/datastore/query/xubh-q36u/0"

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()  # one computation at a time: the first one loads the shared national tables


# ---- county name matching across sources ("Baldwin", "BALDWIN", "St. Tammany Parish", "SAINT TAMMANY") ----

_SUFFIX = re.compile(r"\s+(COUNTY|PARISH|BOROUGH|CENSUS AREA|MUNICIPALITY|CITY AND BOROUGH)$")


def county_key(name: str) -> str:
    s = re.sub(r"[.'`]", "", str(name or "").upper().strip())
    s = _SUFFIX.sub("", s)
    s = re.sub(r"^SAINT\s", "ST ", s)
    return re.sub(r"\s+", " ", s)


# ---- national sources, each loaded once per process ----

def _fetch(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


@lru_cache(maxsize=1)
def _fire_registry() -> pd.DataFrame:
    if not USFA_LOCAL.exists():
        log.info("Downloading USFA National Fire Department Registry to %s", USFA_LOCAL)
        USFA_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        USFA_LOCAL.write_bytes(_fetch(USFA_URL, timeout=180))
    df = pd.read_csv(USFA_LOCAL, dtype=str, skipinitialspace=True).fillna("")
    df["_key"] = df["HQ state"].str.upper() + "|" + df["County"].map(county_key)
    return df


@lru_cache(maxsize=64)
def _cms_hospitals(state: str) -> tuple[dict, ...]:
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"limit": 500, "offset": offset, "conditions[0][property]": "state",
                                    "conditions[0][value]": state})
        page = json.loads(_fetch(f"{CMS_HOSPITALS_URL}?{q}")).get("results", [])
        rows += page
        if len(page) < 500:
            return tuple(rows)
        offset += 500


@lru_cache(maxsize=1)
def _shelters_national() -> pd.DataFrame:
    from .build_pack import _gcs_csv
    df = _gcs_csv("national/fema_nss/fema_nss_shelters_national.csv", dtype=str).fillna("")
    df["_key"] = df["state"].str.upper() + "|" + df["county_parish"].map(county_key)
    return df


@lru_cache(maxsize=1)
def _declarations() -> pd.DataFrame:
    from .build_pack import _gcs_csv
    d = _gcs_csv("national/openfema/disaster_declarations_summaries_v2.csv", dtype=str,
                 usecols=["disasterNumber", "fipsStateCode", "fipsCountyCode", "incidentType",
                          "declarationTitle", "incidentBeginDate"])
    d = d[d["incidentType"].isin(["Hurricane", "Tropical Storm", "Typhoon"])].copy()
    d["fips"] = d["fipsStateCode"].str.zfill(2) + d["fipsCountyCode"].str.zfill(3)
    return d


# ---- per-county resources and history ----

def _num(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def county_shelters(state: str, name: str) -> dict:
    rows = _shelters_national()
    rows = rows[rows["_key"] == f"{state}|{county_key(name)}"]
    items = []
    for r in rows.to_dict("records"):
        lat, lon = pd.to_numeric(r["latitude"], errors="coerce"), pd.to_numeric(r["longitude"], errors="coerce")
        if pd.notna(lat) and pd.notna(lon) and lat < -50 and lon > 10:  # ~3% of NSS rows have lat/lon swapped
            lat, lon = lon, lat
        items.append({"name": r["shelter_name"].strip(), "city": r["city"], "evacuation_capacity": _num(r["evacuation_capacity"]),
                      "generator": r["generator_onsite"].strip().upper() == "YES",
                      "in_surge_zone": r["in_surge_slosh_area"].strip().upper() == "YES",
                      "lat": None if pd.isna(lat) else round(float(lat), 5), "lon": None if pd.isna(lon) else round(float(lon), 5)})
    items.sort(key=lambda s: -s["evacuation_capacity"])
    return {"count": len(items), "evacuation_capacity": sum(s["evacuation_capacity"] for s in items),
            "with_generator": sum(s["generator"] for s in items), "in_surge_zone": sum(s["in_surge_zone"] for s in items),
            "top": items[:5], "source": "FEMA National Shelter System"}


def county_hospitals(state: str, name: str) -> dict:
    key = county_key(name)
    try:
        rows = [h for h in _cms_hospitals(state) if county_key(h.get("countyparish")) == key]
    except Exception as e:  # network/API failure: say so, never substitute
        log.warning("CMS hospitals unavailable for %s: %s", state, e)
        return {"count": None, "error": "CMS hospital list unavailable", "source": "CMS Hospital General Information"}
    items = sorted(({"name": h["facility_name"].title(), "city": h["citytown"].title(), "type": h["hospital_type"],
                     "emergency_services": h.get("emergency_services") == "Yes"} for h in rows),
                   key=lambda h: (not h["emergency_services"], h["name"]))
    return {"count": len(items), "with_emergency_dept": sum(h["emergency_services"] for h in items),
            "top": items[:6], "source": "CMS Hospital General Information (Medicare-certified hospitals)"}


def county_fire(state: str, name: str) -> dict:
    try:
        rows = _fire_registry()
    except Exception as e:
        log.warning("USFA registry unavailable: %s", e)
        return {"departments": None, "error": "USFA fire registry unavailable", "source": "USFA National Fire Department Registry"}
    rows = rows[rows["_key"] == f"{state}|{county_key(name)}"]
    depts = [{"name": r["Fire dept name"], "city": r["HQ city"], "type": r["Dept Type"],
              "stations": _num(r["Number Of Stations"]), "career": _num(r["Active Firefighters - Career"]),
              "volunteer": _num(r["Active Firefighters - Volunteer"]),
              "paid_per_call": _num(r["Active Firefighters - Paid per Call"])} for r in rows.to_dict("records")]
    depts.sort(key=lambda d: -(d["career"] + d["volunteer"] + d["paid_per_call"]))
    return {"departments": len(depts), "stations": sum(d["stations"] for d in depts),
            "career_firefighters": sum(d["career"] for d in depts),
            "volunteer_firefighters": sum(d["volunteer"] for d in depts),
            "paid_per_call_firefighters": sum(d["paid_per_call"] for d in depts),
            "top": depts[:5], "source": "USFA National Fire Department Registry (self-reported by departments)"}


def county_history(fips: str) -> dict:
    from .build_pack import training_rows
    t = training_rows(fips)
    t = t[t["pct_customers_out"] >= 1.0].sort_values("pct_customers_out", ascending=False)
    storms = [{"storm": r["storm_name"], "year": int(r["year"]), "peak_customers_out": _num(r["peak_customers_out"]),
               "pct_customers_out": round(float(r["pct_customers_out"]), 1)} for r in t.to_dict("records")]
    d = _declarations()
    d = d[d["fips"] == fips].drop_duplicates("disasterNumber").sort_values("incidentBeginDate", ascending=False)
    return {"storms_with_outages": len(storms), "worst": storms[:4],
            "fema_declarations": len(d),
            "recent_declarations": [{"title": r["declarationTitle"].title(), "year": r["incidentBeginDate"][:4]}
                                    for r in d.head(3).to_dict("records")],
            "source": "EAGLE-I outages per storm (2014-2025 training table) + OpenFEMA hurricane/tropical declarations"}


# ---- geometry ----

def _densify(path: list[tuple[float, float]], step: int = 12) -> list[tuple[float, float]]:
    if len(path) < 2:
        return path
    out = []
    for (a, b) in zip(path, path[1:]):
        out += [(a[0] + (b[0] - a[0]) * i / step, a[1] + (b[1] - a[1]) * i / step) for i in range(step)]
    return out + [path[-1]]


def _min_dist(lat: float, lon: float, pts: list[tuple[float, float]]) -> float:
    return min(haversine_nm(lat, lon, p[0], p[1]) for p in pts)


# ---- the view ----

def _choose_staging(counties: list[dict], full_track: list[tuple[float, float]], centroids: pd.DataFrame,
                    customers: dict[str, float], names: dict) -> dict | None:
    """Big-enough county, clear of the whole forecast track, closest (by predicted customers out) to the
    counties that need trucks. A siting heuristic, labeled as such in the UI."""
    weights = [(c["lat"], c["lon"], max(c["customers_out"]["median"], 1.0)) for c in counties]
    if not weights:
        return None
    wsum = sum(w for *_, w in weights)
    clat = sum(la * w for la, _, w in weights) / wsum
    clon = sum(lo * w for _, lo, w in weights) / wsum
    best = None
    for r in centroids.itertuples():
        if customers.get(r.county_fips, 0) < STAGING_MIN_CUSTOMERS or haversine_nm(r.county_lat, r.county_lon, clat, clon) > 300:
            continue
        clearance = _min_dist(r.county_lat, r.county_lon, full_track)
        if clearance < STAGING_CLEARANCE_NM:
            continue
        score = sum(haversine_nm(r.county_lat, r.county_lon, la, lo) * w for la, lo, w in weights) / wsum
        if best is None or score < best[0]:
            best = (score, r, clearance)
    if best is None:
        return None
    score, r, clearance = best
    info = names.get(r.county_fips, {})
    return {"fips": r.county_fips, "name": f"{info.get('name', r.county_fips)}, {info.get('state', '')} staging area",
            "county": info.get("name"), "state": info.get("state"),
            "lat": round(float(r.county_lat), 4), "lon": round(float(r.county_lon), 4),
            "clearance_from_track_nm": round(clearance), "avg_distance_to_counties_nm": round(score),
            "method": f"Largest-need-weighted nearest county with >= {STAGING_MIN_CUSTOMERS:,} utility customers "
                      f"that stays >= {STAGING_CLEARANCE_NM:.0f} nm from the whole NHC forecast track"}


def predict_counties(fips_list: list[str], advisory: dict, points: list, tau: int, skipped: list) -> list[dict]:
    """The trained model for these counties at one forecast snapshot. A county whose real feature data has a
    gap is appended to `skipped` (never filled in); the rest are still predicted. Each result gains
    customers_out and trucks_needed ranges."""
    from models.pipeline import MissingForecastDataError, get_name_lookup, run_impact_pipeline
    from models.live_inference import UnresolvedLiveFeatureError

    def run(fl):
        return run_impact_pipeline(county_fips=fl, advisory=advisory, forecast_points=points, lead_time_h=tau)["counties"]
    try:
        preds = run(fips_list)
    except (UnresolvedLiveFeatureError, MissingForecastDataError):
        preds = []
        for f in fips_list:  # isolate the counties whose real data has a gap
            try:
                preds += run([f])
            except (UnresolvedLiveFeatureError, MissingForecastDataError) as e:
                skipped.append({"fips": f, "name": get_name_lookup().get(f, {}).get("name"), "reason": str(e)[:200]})
    for c in preds:
        q, cust = c["pct_customers_out"], c["customers_served"]
        c["customers_out"] = {k: round(q[k] * cust / 100) for k in ("low", "median", "high")}
        c["trucks_needed"] = {k: math.ceil(v / CUSTOMERS_OUT_PER_TRUCK) for k, v in c["customers_out"].items()}
    return preds


def _compute(storm_id: str) -> dict:
    from models.pipeline import get_name_lookup, get_static_tables

    poller = get_poller()
    storm = next((s for s in poller.get_active_storms() if s["storm_id"] == storm_id), None)
    if storm is None:
        raise KeyError(storm_id)
    points = poller.get_forecast_points(storm_id)
    cycle = max(p.cycle_init_time_utc for p in points)
    latest = sorted((p for p in points if p.cycle_init_time_utc == cycle), key=lambda p: p.tau_h)

    now = datetime.fromisoformat(storm["last_update_utc"].replace("Z", "+00:00")) if storm.get("last_update_utc") else datetime.now(timezone.utc)
    as_utc = lambda dt: dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    ahead = [p for p in latest if as_utc(p.valid_time_utc) >= now]
    path = [(storm["lat"], storm["lon"])] + [(p.lat, p.lon) for p in ahead]
    full_track = _densify(path)
    # Exposure: the stretch of track where the storm is still at least tropical-storm force.
    exposed = [p for p in ahead if p.vmax_kt >= TS_FORCE_KT]
    exp_path = _densify(([(storm["lat"], storm["lon"])] if storm["intensity_kt"] >= TS_FORCE_KT else []) +
                        [(p.lat, p.lon) for p in exposed])
    # Snapshot candidates for the model: real forecast points, nearest to "now" first.
    snap_points = [p for p in latest if as_utc(p.valid_time_utc) >= now] or latest[-1:]
    snap_points = [p for p in snap_points if p.vmax_kt >= TS_FORCE_KT] or snap_points[:1]

    static = get_static_tables()
    centroids = static["centroids"]
    names = get_name_lookup()
    customers = dict(zip(static["mcc"]["county_fips"], static["mcc"]["mcc_customers"]))

    base = {"storm_id": storm_id, "storm_name": storm["name"], "forecast_cycle_utc": as_utc(cycle).isoformat(),
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "risk_radius_nm": RISK_RADIUS_NM, "skipped": [], "counties": [], "staging": None,
            "assumptions": [f"ASSUMPTION: 1 utility truck per {CUSTOMERS_OUT_PER_TRUCK:,} predicted customers out "
                            "(planning rule of thumb, not data)."],
            "caveats": []}
    if storm_id[:2] != "AL":
        base["caveats"].append("The outage model is trained mostly on Atlantic storms (one East Pacific storm, "
                               "Hilary 2023); treat Pacific-storm predictions as lower confidence.")
    if not exp_path:
        base["note"] = "The forecast keeps this storm below tropical-storm force; no county exposure computed."
        return base

    cand = []
    for r in centroids.itertuples():
        # cheap bounding filter before the per-point distance
        if not any(abs(r.county_lat - la) < 3 and abs(r.county_lon - lo) < 3.5 for la, lo in exp_path[::4] + exp_path[-1:]):
            continue
        d = _min_dist(r.county_lat, r.county_lon, exp_path)
        if d <= RISK_RADIUS_NM:
            cand.append((d, r.county_fips, float(r.county_lat), float(r.county_lon)))
    cand.sort()
    cand = cand[:MAX_MODEL_COUNTIES]
    if not cand:
        base["note"] = f"No US county lies within {RISK_RADIUS_NM:.0f} nm of the forecast track while it is at tropical-storm force."
        return base

    # Group counties by their closest real forecast point, then one model run per group.
    groups: dict[int, list] = {}
    for d, fips, la, lo in cand:
        snap = min(snap_points, key=lambda p: haversine_nm(la, lo, p.lat, p.lon))
        groups.setdefault(snap.tau_h, []).append((fips, d, la, lo, snap))
    adv = {"storm_id": storm_id, "storm_name": storm["name"], "advisory_number": 0}
    results = []
    for tau, members in groups.items():
        by_fips = {m[0]: m for m in members}
        for c in predict_counties([m[0] for m in members], adv, latest, tau, base["skipped"]):
            fips, d, la, lo, snap = by_fips[c["fips"]]
            results.append({
                "fips": fips, "name": c["name"], "state": c["state"], "lat": round(la, 4), "lon": round(lo, 4),
                "risk_tier": c["risk_tier"], "pct_customers_out": c["pct_customers_out"], "customers_served": c["customers_served"],
                "customers_out": c["customers_out"], "why": c["why"], "severe_uncertainty_caveat": c.get("severe_uncertainty_caveat"),
                "distance_to_track_nm": round(d), "closest_forecast_utc": as_utc(snap.valid_time_utc).isoformat(),
                "forecast_wind_kt_at_closest": snap.vmax_kt, "trucks_needed": c["trucks_needed"],
            })

    # Most predicted customers out first (what drives crews and trucks); green-tier counties only fill gaps.
    results.sort(key=lambda c: (c["risk_tier"] == "green", -c["customers_out"]["median"]))
    top = results[:MAX_COUNTIES]

    pack_slugs = {p["fips"]: p.get("slug") for p in store.index()}
    for c in top:
        c["shelters"] = county_shelters(c["state"], c["name"])
        c["hospitals"] = county_hospitals(c["state"], c["name"])
        c["fire"] = county_fire(c["state"], c["name"])
        c["history"] = county_history(c["fips"])
        c["pack_slug"] = pack_slugs.get(c["fips"])

    base["counties"] = top
    base["counties_evaluated"] = len(results)
    needy = [c for c in top if c["trucks_needed"]["median"] > 0] or top
    base["staging"] = _choose_staging(needy, full_track, centroids, customers, names)
    base["trucks_needed_total"] = {k: sum(c["trucks_needed"][k] for c in top) for k in ("low", "median", "high")}
    base["sources"] = sorted({c[k]["source"] for c in top for k in ("shelters", "hospitals", "fire", "history")})
    base["model_source"] = "Quantile XGBoost outage model (outage_xgb_real_v1) + conformal calibration, on the NHC official forecast"
    return base


def storm_risk(storm_id: str) -> dict:
    """Cached per storm for CACHE_TTL_SEC. Raises KeyError (storm not active) or AtcfSourceError (no NHC forecast)."""
    storm_id = storm_id.upper()
    hit = _cache.get(storm_id)
    if hit and time.time() - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    with _lock:
        hit = _cache.get(storm_id)
        if hit and time.time() - hit[0] < CACHE_TTL_SEC:
            return hit[1]
        view = _compute(storm_id)
        _cache[storm_id] = (time.time(), view)
        return view
