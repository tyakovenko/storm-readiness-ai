"""Build the processed Dallas tables from raw/dallas.

    python -m dallas.build            # from backend/: reads data/raw/dallas, writes data/processed/dallas
    python -m dallas.build --push     # also uploads processed/dallas to GCS

Inputs (pull with `python data/sync_cloud_data.py pull --dataset dallas`):
  dallas311/*.csv, noaa/*.csv, fema/*.json, eaglei/*.csv, weather/*.csv,
  gis/council_districts.geojson, shelters/nss_shelters_dallas_county.csv
Outputs: storms.json, assets.json, districts.geojson, manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import sources as S

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw" / "dallas"
OUT = REPO / "data" / "processed" / "dallas"
BUCKET = "gs://uc3-storm-impact-intelligence-data"

# EAGLE-I customer total for Dallas County (eaglei_county_customers_fall_2025.csv).
CUSTOMERS_TOTAL = 1178610
# A 311 type counts as storm-driven only if the storm days run well above the
# baseline days. Both bars must pass so one-off spikes in rare types don't count.
MIN_RATIO = 2.0
MIN_EXCESS = 10


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def _days(a: str, b: str) -> int:
    return (_d(b) - _d(a)).days + 1


def _sector(req_type: str) -> str:
    t = req_type.lower()
    for sector, keys in S.SECTOR_RULES:
        if any(k in t for k in keys):
            return sector
    return "other"


def build_311(storm: dict) -> dict:
    ev0, ev1 = storm["event"]
    cx0, cx1 = storm["context"]
    files = list((RAW / "dallas311").glob(f"311_{storm['id']}_*.csv"))
    if len(files) != 1:
        raise FileNotFoundError(f"expected one 311 file for {storm['id']}, found {files}")
    ev_days = _days(ev0, ev1)
    base_days = _days(cx0, cx1) - ev_days
    ev_counts, base_counts = Counter(), Counter()
    by_district = defaultdict(Counter)  # district -> sector -> storm-day count
    rows = 0
    with open(files[0], newline="") as f:
        for r in csv.DictReader(f):
            rows += 1
            day = r["created_date"][:10]
            t = r["service_request_type"]
            if ev0 <= day <= ev1:
                ev_counts[t] += 1
                by_district[(r.get("city_council_district") or "").lstrip("0")][_sector(t)] += 1
            else:
                base_counts[t] += 1

    surges = []
    for t, n in ev_counts.items():
        base_rate = base_counts[t] / base_days
        expected = base_rate * ev_days
        excess = n - expected
        ratio = n / expected if expected else float("inf")
        if excess >= MIN_EXCESS and ratio >= MIN_RATIO and _sector(t) != "other":
            surges.append({"request_type": t, "sector": _sector(t), "storm_days_count": n,
                           "expected_count": round(expected, 1), "excess": round(excess),
                           "ratio": None if ratio == float("inf") else round(ratio, 1)})
    surges.sort(key=lambda s: -s["excess"])

    sector_excess = Counter()
    for s in surges:
        sector_excess[s["sector"]] += s["excess"]
    districts = {d: dict(c) for d, c in by_district.items() if d.isdigit()}
    return {
        "rows_in_file": rows,
        "storm_days": ev_days,
        "baseline_days": base_days,
        "total_storm_days": sum(ev_counts.values()),
        "total_expected": round(sum(base_counts.values()) / base_days * ev_days),
        "surges": surges,
        "excess_by_sector": dict(sector_excess),
        "storm_requests_by_district": districts,
    }


def build_weather(storm: dict) -> dict | None:
    f = RAW / "weather" / f"asos_dfw_{storm['id']}.csv"
    if not f.exists():
        return None
    # Only the event dates ±1 day: the raw file is wider and an unrelated cold
    # night before the storm would otherwise set the metrics (Jan 7 for winter_2025).
    lo = (_d(storm["event"][0]) - timedelta(days=1)).isoformat()
    hi = (_d(storm["event"][1]) + timedelta(days=1)).isoformat()
    obs = []
    with open(f, newline="") as fh:
        for r in csv.DictReader(fh):
            if r["tmpf"] and lo <= r["valid"][:10] <= hi:
                obs.append(r)
    temps = [float(r["tmpf"]) for r in obs]
    # Longest run of consecutive hourly obs strictly below 32°F ~ hours below freezing.
    # Strict <32 matches published counts (Fern 2026: 58 h, DMN 2026-02-09).
    run = best = 0
    for t in temps:
        run = run + 1 if t < 32 else 0
        best = max(best, run)

    def _hours(code: str) -> int:
        # wxcodes like "-FZRA BR" or "+PL": substring match catches intensity prefixes.
        return sum(1 for r in obs if code in (r["wxcodes"] or ""))

    def _sum(col: str) -> float:
        # 0.0001 is IEM's "trace" marker; count it as zero.
        return round(sum(float(r[col]) for r in obs if r.get(col) and float(r[col]) > 0.001), 2)

    # Precip/snow totals come from the QC'd daily record (GHCN-D), not ASOS p01i:
    # the hourly gauge over-reads in sleet (1.7 in/hr at DFW on 2026-01-24).
    daily = json.loads((RAW / "weather" / f"ghcn_dfw_{storm['id']}.json").read_text())
    return {
        "station": "KDFW (DFW Airport)",
        "min_temp_f": min(temps),
        "hours_below_freezing": best,
        "freezing_rain_hours": _hours("FZRA"),
        "sleet_hours": _hours("PL"),
        "snow_hours": _hours("SN"),
        "ice_accretion_in": _sum("ice_accretion_1hr"),
        "precip_in": round(sum(float(d.get("PRCP") or 0) for d in daily), 2),
        "snowfall_in": round(sum(float(d.get("SNOW") or 0) for d in daily), 1),
        "window": [obs[0]["valid"], obs[-1]["valid"]],
        "source": "Iowa Environmental Mesonet ASOS archive (hourly) + NOAA GHCN-Daily USW00003927 (totals over event dates)",
    }


def build_outages(storm: dict) -> dict | None:
    year = storm["event"][0][:4]
    f = RAW / "eaglei" / f"eaglei_48113_{year}.csv"
    if not f.exists():
        return None
    ev0 = _d(storm["event"][0])
    ev1 = _d(storm["event"][1]) + timedelta(days=2)  # restoration tail
    peak, peak_t, hours_over = 0, None, 0
    with open(f, newline="") as fh:
        for r in csv.DictReader(fh):
            t = datetime.fromisoformat(r["run_start_time"])
            if ev0 <= t.date() <= ev1:
                n = int(float(r["customers_out"] or 0))
                if n > peak:
                    peak, peak_t = n, r["run_start_time"]
                if n >= 10000:
                    hours_over += 0.25  # 15-minute snapshots
    return {"peak_customers_out": peak, "peak_time": peak_t,
            "peak_pct_customers": round(100 * peak / CUSTOMERS_TOTAL, 2),
            "hours_over_10k_out": hours_over, "customers_total": CUSTOMERS_TOTAL,
            "source": "EAGLE-I (ORNL), 15-min county snapshots"}


def build_noaa(storm: dict) -> dict:
    ev0, ev1 = _d(storm["event"][0]) - timedelta(days=1), _d(storm["event"][1]) + timedelta(days=1)
    rows = []
    with open(RAW / "noaa" / "storm_events_dallas_county_2000_2026.csv", newline="") as f:
        for r in csv.DictReader(f):
            ym, day = r["BEGIN_YEARMONTH"], int(r["BEGIN_DAY"])
            d = date(int(ym[:4]), int(ym[4:]), day)
            if ev0 <= d <= ev1:
                rows.append(r)
    episodes = {}
    for r in rows:
        episodes.setdefault(r["EPISODE_ID"], r["EPISODE_NARRATIVE"].strip())
    return {
        "events": [{"event_type": r["EVENT_TYPE"], "begin": f"{r['BEGIN_YEARMONTH']}{int(r['BEGIN_DAY']):02d}",
                    "deaths": int(r["DEATHS_DIRECT"] or 0) + int(r["DEATHS_INDIRECT"] or 0),
                    "injuries": int(r["INJURIES_DIRECT"] or 0) + int(r["INJURIES_INDIRECT"] or 0),
                    "damage_property": r["DAMAGE_PROPERTY"] or None,
                    "narrative": r["EVENT_NARRATIVE"].strip()[:600] or None} for r in rows],
        "episode_narratives": [n[:1200] for n in episodes.values() if n],
        "source": "NOAA NCEI Storm Events Database",
    }


def build_fema(storm: dict) -> dict:
    nums = [int(x.split("-")[1]) for x in storm["fema"]]
    pa = json.load(open(RAW / "fema" / "pa_funded_projects_48113.json"))["PublicAssistanceFundedProjectsDetails"]
    proj = [p for p in pa if p["disasterNumber"] in nums]
    by_cat = Counter()
    for p in proj:
        by_cat[p["damageCategoryCode"]] += p.get("projectAmount") or 0
    return {"declarations": storm["fema"], "pa_projects": len(proj),
            "pa_amount_usd": round(sum(by_cat.values())),
            "pa_amount_by_category_usd": {k: round(v) for k, v in sorted(by_cat.items())},
            "caveat": "PA county = applicant's county, not damage site",
            "source": "OpenFEMA PublicAssistanceFundedProjectsDetails v2"}


def build_assets() -> dict:
    nss = list(csv.DictReader(open(RAW / "shelters" / "nss_shelters_dallas_county.csv", newline="")))
    cap = [int(float(r["evacuation_capacity"] or 0)) for r in nss]
    largest = sorted(nss, key=lambda r: -int(float(r["evacuation_capacity"] or 0)))[:10]
    return {
        "inclement_weather_shelters": S.SHELTER_SITES,
        "shelter_history": S.SHELTER_HISTORY,
        "resources": S.RESOURCES,
        "departments": S.DEPARTMENTS,
        "evacuee_shelters_nss": {
            "count": len(nss), "with_evacuation_capacity": sum(1 for c in cap if c > 0),
            "total_evacuation_capacity": sum(cap),
            "largest": [{"name": r["shelter_name"], "city": r["city"],
                         "evacuation_capacity": int(float(r["evacuation_capacity"] or 0)),
                         "post_impact_capacity": int(float(r["post_impact_capacity"] or 0))} for r in largest],
            "source": "FEMA National Shelter System (gis.fema.gov NSS layer 5)",
        },
    }


def build_districts(storms: list[dict]) -> dict:
    geo = json.load(open(RAW / "gis" / "council_districts.geojson"))
    # Each district's share of storm-day transport requests (sanding, signals, streets)
    # across all winter storms: the planner's weight for spreading trucks.
    tot = Counter()
    for s in storms:
        if s["hazard"] != "winter":
            continue
        for d, sectors in s["impacts_311"]["storm_requests_by_district"].items():
            tot[d] += sectors.get("transport", 0)
    grand = sum(tot.values()) or 1
    for f in geo["features"]:
        d = str(f["properties"]["district"]).lstrip("0")
        f["properties"] = {"district": d, "council_member": f["properties"].get("councilper"),
                           "winter_transport_requests": tot.get(d, 0),
                           "winter_transport_share": round(tot.get(d, 0) / grand, 4)}
    return geo


def build() -> dict:
    storms = []
    for s in S.STORMS:
        rec = {k: s[k] for k in ("id", "name", "hazard")}
        rec["event_dates"] = list(s["event"])
        rec["weather"] = build_weather(s)
        rec["outages"] = build_outages(s)
        rec["impacts_311"] = build_311(s)
        rec["noaa"] = build_noaa(s)
        rec["fema"] = build_fema(s)
        rec["city_response"] = S.RESPONSE_FACTS.get(s["id"], [])
        storms.append(rec)
        log.info("built %s", s["id"])
    OUT.mkdir(parents=True, exist_ok=True)
    tables = {"storms.json": storms, "assets.json": build_assets(),
              "districts.geojson": build_districts(storms)}
    for name, obj in tables.items():
        (OUT / name).write_text(json.dumps(obj, indent=1))
    manifest = {"built_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "storms": [s["id"] for s in storms], "files": sorted(tables)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="upload processed tables to GCS")
    args = ap.parse_args()
    print(json.dumps(build(), indent=1))
    if args.push:
        subprocess.run(["gcloud", "storage", "cp", "-r", str(OUT), f"{BUCKET}/processed/"], check=True)


if __name__ == "__main__":
    main()
