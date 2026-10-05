"""Build the REAL hurricane training table: one row per (storm, county).

Label: EAGLE-I peak % of customers out during the storm window (max customers_out / MCC).
Features: the 13 FEATURE_COLUMNS, built through schema.CountyFeatures + features_to_dataframe
so training uses exactly the transforms the model sees at inference.

    python -m models.build_training_table --out gs://uc3-storm-impact-intelligence-data/processed/hurricane/training_table.csv
    python -m models.build_training_table --out /tmp/t.csv --years 2023 --max-storms 1   # quick check

Inputs (GCS raw/, or data/raw/ locally): hurdat2/*, nri, svi, oni, national/reference/{2024_Gaz_counties_national.txt,
eaglei_mcc.csv}, national/tree_canopy/tree_canopy_by_county.csv. EAGLE-I per-year CSVs are streamed from figshare
(item 24237376) and filtered on the fly; nothing large is stored.

Approximations (documented, not hidden): wind at a county uses a Rankine-type decay outside the radius of maximum
wind, v = vmax * (rmw / d) ** 0.5, from the HURDAT2 best-track vmax (already reflects weakening over land). rmw is
HURDAT2's own value when present (2021+), else 20 nm. Gust = 1.25 x sustained (schema default). lead_time_h = 0 for
every row: best tracks have no forecast lead time, so the model learns impact from conditions only.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import math
import os
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .dataset import get_gcs_blob_bytes, load_county_static_lookup
from .schema import FEATURE_COLUMNS, CountyFeatures, features_to_dataframe

log = logging.getLogger(__name__)

REPO_DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data")
MAX_DIST_NM = 150.0          # counties farther than this from the track are not candidates
MIN_STORM_WIND_KT = 34.0     # a storm is kept only if some county saw tropical-storm-force wind
DEFAULT_RMW_NM = 20.0
WINDOW_BEFORE_H, WINDOW_AFTER_H = 12, 72   # label window around the hours the county was within MAX_DIST_NM
MIN_ROWS = 300               # fail loudly rather than train on a near-empty table

# EAGLE-I per-year CSVs on figshare (item 24237376). 2014 coverage starts Nov 1.
EAGLEI_FILES = {2014: 42547717, 2015: 42547822, 2016: 42547825, 2017: 42547828, 2018: 42547879, 2019: 42547885,
                2020: 42547894, 2021: 42547891, 2022: 42547897, 2023: 44574907, 2024: 53581661, 2025: 62164877}
CONUS_EXCLUDE = {"02", "15", "60", "66", "69", "72", "78"}


# ---------- IO ----------

def read_bytes(rel: str) -> bytes:
    """data/raw/<rel> locally if present, else gs://<bucket>/raw/<rel>. Raises if neither."""
    local = os.path.join(REPO_DATA, "raw", rel)
    if os.path.exists(local):
        return open(local, "rb").read()
    return get_gcs_blob_bytes(f"raw/{rel}")


def write_text(path: str, text: str) -> None:
    if path.startswith("gs://"):
        from google.cloud import storage
        bucket, blob = path[5:].split("/", 1)
        storage.Client().bucket(bucket).blob(blob).upload_from_string(text)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        open(path, "w").write(text)


# ---------- storms ----------

@dataclass
class Storm:
    id: str
    name: str
    year: int
    t: np.ndarray        # hourly datetimes (UTC)
    lat: np.ndarray
    lon: np.ndarray
    vmax: np.ndarray     # kt
    rmw: np.ndarray      # nm


def _coord(s: str) -> float:
    s = s.strip()
    v = float(s[:-1])
    return -v if s[-1] in "SW" else v


def parse_hurdat(text: str, years: set[int]) -> list[Storm]:
    storms, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        head = [x.strip() for x in lines[i].split(",")]
        sid, name, n = head[0], head[1], int(head[2])
        year = int(sid[4:8])
        rows = lines[i + 1:i + 1 + n]
        i += 1 + n
        if year not in years:
            continue
        ts, la, lo, vm, rm = [], [], [], [], []
        for r in rows:
            f = [x.strip() for x in r.split(",")]
            ts.append(datetime.strptime(f[0] + f[1], "%Y%m%d%H%M").replace(tzinfo=timezone.utc))
            la.append(_coord(f[4])); lo.append(_coord(f[5])); vm.append(float(f[6]))
            # Field 21 (index 20) = radius of max wind, nm; -999 before 2021.
            rmw = float(f[20]) if len(f) > 20 and f[20] not in ("", "-999") else -1
            rm.append(rmw if rmw > 0 else DEFAULT_RMW_NM)
        # Interpolate to hourly so distance minima aren't missed between 6-h fixes.
        t0 = ts[0]
        hrs = np.array([(t - t0).total_seconds() / 3600 for t in ts])
        grid = np.arange(0, hrs[-1] + 1e-9, 1.0)
        storms.append(Storm(sid, name.title(), year, np.array([t0 + timedelta(hours=float(h)) for h in grid]),
                            np.interp(grid, hrs, la), np.interp(grid, hrs, lo),
                            np.interp(grid, hrs, vm), np.interp(grid, hrs, rm)))
    return storms


def haversine_nm(lat1, lon1, lat2, lon2):
    r = 3440.065  # Earth radius, nm
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def storm_county_features(s: Storm, counties: pd.DataFrame) -> pd.DataFrame:
    """Per county near the track: max wind at county, closest distance, motion at closest approach, label window."""
    clat, clon = counties["lat"].to_numpy(), counties["lon"].to_numpy()
    d = haversine_nm(s.lat[:, None], s.lon[:, None], clat[None, :], clon[None, :])   # hours x counties
    rmw = s.rmw[:, None]
    wind = np.where(d <= rmw, s.vmax[:, None], s.vmax[:, None] * np.sqrt(rmw / np.maximum(d, 1e-6)))
    near = d <= MAX_DIST_NM
    keep = near.any(axis=0)
    if not keep.any():
        return pd.DataFrame()
    rows = []
    # Motion vector per hour (deg/h); forward speed in kt from successive hourly positions.
    dlat, dlon = np.gradient(s.lat), np.gradient(s.lon)
    fwd = haversine_nm(s.lat, s.lon, s.lat + dlat, s.lon + dlon)
    for j in np.where(keep)[0]:
        k = int(np.argmin(d[:, j]))
        hours = np.where(near[:, j])[0]
        # Right of track (N hemisphere): cross product of motion and storm->county vectors is negative.
        cross = dlon[k] * (clat[j] - s.lat[k]) - dlat[k] * (clon[j] - s.lon[k])
        rows.append({
            "fips": counties["fips"].iat[j], "dist_to_track_nm": round(float(d[k, j]), 1),
            "max_wind_kt": round(float(wind[:, j].max()), 1), "forward_speed_kt": round(float(fwd[k]), 1),
            "quadrant_right": int(cross < 0),
            "window_start": s.t[hours[0]] - timedelta(hours=WINDOW_BEFORE_H),
            "window_end": s.t[hours[-1]] + timedelta(hours=WINDOW_AFTER_H),
        })
    out = pd.DataFrame(rows)
    return out if out["max_wind_kt"].max() >= MIN_STORM_WIND_KT else pd.DataFrame()


# ---------- static county data ----------

def load_counties() -> pd.DataFrame:
    g = pd.read_csv(io.BytesIO(read_bytes("national/reference/2024_Gaz_counties_national.txt")), sep="\t", dtype={"GEOID": str})
    g.columns = [c.strip() for c in g.columns]
    g = g[~g["GEOID"].str[:2].isin(CONUS_EXCLUDE)]
    return pd.DataFrame({"fips": g["GEOID"].str.zfill(5), "lat": g["INTPTLAT"].astype(float), "lon": g["INTPTLONG"].astype(float)})


def load_customers() -> dict[str, int]:
    # MCC.csv has a BOM and integer FIPS (lost leading zero).
    m = pd.read_csv(io.BytesIO(read_bytes("national/reference/eaglei_mcc.csv")), encoding="utf-8-sig")
    return {str(int(f)).zfill(5): int(c) for f, c in zip(m["County_FIPS"], m["Customers"]) if pd.notnull(c) and c > 0}


def load_canopy() -> dict[str, float]:
    c = pd.read_csv(io.BytesIO(read_bytes("national/tree_canopy/tree_canopy_by_county.csv")), dtype={"fips": str})
    c = c[c["tcc_mean_pct"].notna()]
    return dict(zip(c["fips"].str.zfill(5), c["tcc_mean_pct"].astype(float)))


def load_oni() -> dict[tuple[str, int], float]:
    out = {}
    for line in read_bytes("oni/oni.ascii.txt").decode().splitlines():
        p = line.split()
        if len(p) == 4 and p[0] != "SEAS":
            out[(p[0], int(p[1]))] = float(p[3])
    return out


SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]


# ---------- labels ----------

def eaglei_peaks(year: int, windows: pd.DataFrame) -> pd.DataFrame:
    """Stream one EAGLE-I year and return max customers_out per (storm_id, fips) inside each window."""
    url = f"https://ndownloader.figshare.com/files/{EAGLEI_FILES[year]}"
    want = set(windows["fips"])
    best: dict[tuple[str, str], tuple[float, int]] = {}
    req = urllib.request.Request(url, headers={"User-Agent": "storm-readiness-ai/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        reader = pd.read_csv(resp, chunksize=2_000_000, dtype={"fips_code": str}, low_memory=False)
        for chunk in reader:
            out_col = "customers_out" if "customers_out" in chunk.columns else "sum"   # 2023 file uses "sum"
            chunk["fips"] = chunk["fips_code"].str.zfill(5)
            chunk = chunk[chunk["fips"].isin(want)]
            if chunk.empty:
                continue
            chunk["t"] = pd.to_datetime(chunk["run_start_time"], utc=True)
            m = chunk[["fips", "t", out_col]].merge(windows, on="fips")
            m = m[(m["t"] >= m["window_start"]) & (m["t"] <= m["window_end"])]
            for (sid, f), g in m.groupby(["storm_id", "fips"]):
                prev = best.get((sid, f), (0.0, 0))
                best[(sid, f)] = (max(prev[0], float(g[out_col].max())), prev[1] + len(g))
            log.info("EAGLE-I %s: through %s, %d storm-county pairs seen", year, chunk["t"].max(), len(best))
    return pd.DataFrame([{"storm_id": s, "fips": f, "peak_customers_out": v[0], "eaglei_rows": v[1]}
                         for (s, f), v in best.items()])


# ---------- build ----------

def build(years: list[int], max_storms: int | None = None) -> tuple[pd.DataFrame, dict]:
    counties = load_counties()
    storms = []
    for basin in ("hurdat2_atlantic.txt", "hurdat2_pacific.txt"):
        storms += parse_hurdat(read_bytes(f"hurdat2/{basin}").decode(), set(years))
    near = []
    for s in storms:
        f = storm_county_features(s, counties)
        if not f.empty:
            f["storm_id"], f["storm_name"], f["year"] = s.id, s.name, s.year
            f["month"] = s.t[int(len(s.t) / 2)].month
            near.append(f)
    if max_storms:
        near = near[:max_storms]
    cand = pd.concat(near, ignore_index=True)
    log.info("%d storms with US county impact, %d storm-county candidates", cand["storm_id"].nunique(), len(cand))

    labels = []
    for y in sorted(cand["year"].unique()):
        w = cand[cand["year"] == y][["storm_id", "fips", "window_start", "window_end"]].copy()
        w["window_start"] = pd.to_datetime(w["window_start"], utc=True)
        w["window_end"] = pd.to_datetime(w["window_end"], utc=True)
        labels.append(eaglei_peaks(int(y), w))
    lab = pd.concat(labels, ignore_index=True) if labels else pd.DataFrame(
        columns=["storm_id", "fips", "peak_customers_out", "eaglei_rows"])

    static, customers, canopy, oni = load_county_static_lookup(), load_customers(), load_canopy(), load_oni()
    t = cand.merge(lab, on=["storm_id", "fips"], how="left")
    drops = {"no_eaglei_rows": int(t["eaglei_rows"].isna().sum()),
             "no_customer_count": int((~t["fips"].isin(customers)).sum()),
             "no_static_nri_svi": int((~t["fips"].isin(static)).sum()),
             "no_tree_canopy": int((~t["fips"].isin(canopy)).sum())}
    t = t[t["eaglei_rows"].notna() & t["fips"].isin(customers) & t["fips"].isin(static) & t["fips"].isin(canopy)]

    feats, out = [], []
    for r in t.itertuples():
        st = static[r.fips]
        cust = customers[r.fips]
        feats.append(CountyFeatures(
            fips=r.fips, name=st["name"], state=st["state"], max_wind_kt=r.max_wind_kt,
            dist_to_track_nm=r.dist_to_track_nm, forward_speed_kt=r.forward_speed_kt, quadrant_right=r.quadrant_right,
            population=st["population"], customers_served=cust, tree_canopy_pct=canopy[r.fips],
            nri_risk_score=st["nri_risk_score"], nri_eal_building=st["nri_eal_building"],
            svi_overall=st["svi_overall"], oni_anomaly=oni.get((SEASONS[r.month - 1], r.year), 0.0), lead_time_h=0.0))
        out.append({"storm_id": r.storm_id, "storm_name": r.storm_name, "year": r.year, "fips": r.fips,
                    "county": st["name"], "state": st["state"], "customers": cust,
                    "peak_customers_out": r.peak_customers_out, "eaglei_rows": int(r.eaglei_rows),
                    "pct_customers_out": round(min(100.0, 100.0 * r.peak_customers_out / cust), 3),
                    "window_start": r.window_start, "window_end": r.window_end})
    table = pd.concat([pd.DataFrame(out), features_to_dataframe(feats)], axis=1)
    manifest = {
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "years": years, "rows": len(table), "storms": int(table["storm_id"].nunique()) if len(table) else 0,
        "storm_list": sorted(table["storm_name"].astype(str) + " " + table["year"].astype(str)) if len(table) else [],
        "candidates": len(cand), "dropped": drops,
        "label": "EAGLE-I max customers_out in window / EAGLE-I MCC customers, %",
        "approximations": ["wind = vmax*(rmw/d)^0.5 outside rmw", "rmw default 20 nm before 2021",
                           "gust = 1.25 x sustained", "lead_time_h = 0", f"window -{WINDOW_BEFORE_H}h/+{WINDOW_AFTER_H}h",
                           f"candidates within {MAX_DIST_NM} nm"],
        "feature_columns": FEATURE_COLUMNS,
    }
    manifest["storm_list"] = sorted(set(manifest["storm_list"]))
    return table, manifest


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="training_table.csv path (local or gs://)")
    ap.add_argument("--years", default="2014-2025", help="e.g. 2014-2025 or 2023")
    ap.add_argument("--max-storms", type=int, default=None, help="limit for quick checks")
    ap.add_argument("--min-rows", type=int, default=MIN_ROWS)
    a = ap.parse_args()
    lo, _, hi = a.years.partition("-")
    years = list(range(int(lo), int(hi or lo) + 1))
    table, manifest = build(years, a.max_storms)
    if len(table) < a.min_rows:
        raise SystemExit(f"Only {len(table)} rows (< {a.min_rows}); refusing to write a table this small. {manifest['dropped']}")
    write_text(a.out, table.to_csv(index=False))
    write_text(a.out.rsplit(".", 1)[0] + "_manifest.json", json.dumps(manifest, indent=1, default=str))
    log.info("wrote %d rows, %d storms -> %s", len(table), manifest["storms"], a.out)


if __name__ == "__main__":
    main()
