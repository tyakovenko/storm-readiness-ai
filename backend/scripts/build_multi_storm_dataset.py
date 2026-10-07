"""Phase 3L: scale the validated Michael pipeline (Phase 3G/3K) to multiple
curated Atlantic hurricanes, via storm_pipeline.build_storm_dataset() (the
exact same per-storm logic Michael uses -- no feature/target redesign).

Candidate storms (ATCF files confirmed present under raw/atcf/ or, for
Michael, raw/national/atcf_archive_2014_2025/): Florence 2018 (AL062018),
Michael 2018 (AL142018), Ian 2022 (AL092022), Idalia 2023 (AL102023),
Helene 2024 (AL092024), Milton 2024 (AL142024). Otis 2023 (Eastern Pacific,
Mexico landfall) is explicitly excluded -- US county EAGLE-I/Census data has
no bearing on a Mexican county, there is nothing to "genuinely support" it.

Run from the backend/ directory: PYTHONPATH=.. ./.venv/Scripts/python.exe scripts/build_multi_storm_dataset.py
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from backend.models import dataset
from backend.models.county_geometry import load_county_centroids
from backend.models.hurdat2 import parse_hurdat2_storms
from backend.models.outage_target import build_customer_denominator_table, load_mcc_customers
from backend.models.schema import FEATURE_COLUMNS
from backend.scripts.storm_pipeline import build_storm_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

HURDAT2_PATH = DATA_DIR / "raw" / "hurdat2" / "hurdat2_atlantic.txt"
CENSUS_SHP_PATH = DATA_DIR / "raw" / "census" / "counties" / "cb_2025_us_county_500k.shp"
ATCF_DIR = DATA_DIR / "raw" / "atcf"
EAGLEI_DIR = DATA_DIR / "raw" / "census" / "EAGLE I"
EAGLEI_ZIP_REL_PATH = "raw/census/EAGLE I/24237376.zip"
MCC_LOCAL_CACHE = EAGLEI_DIR / "MCC.csv"

OUTPUT_DIR = DATA_DIR / "processed" / "multi_storm_2018_2024"


@dataclass(frozen=True)
class StormConfig:
    storm_id: str
    storm_name: str
    atcf_path: Path
    eaglei_year: int


STORM_CONFIGS = [
    StormConfig("AL062018", "FLORENCE", ATCF_DIR / "aal062018.dat.gz", 2018),
    StormConfig("AL142018", "MICHAEL", DATA_DIR / "raw" / "national" / "atcf_archive_2014_2025" / "aal142018.dat.gz", 2018),
    StormConfig("AL092022", "IAN", ATCF_DIR / "aal092022.dat.gz", 2022),
    StormConfig("AL102023", "IDALIA", ATCF_DIR / "aal102023.dat.gz", 2023),
    StormConfig("AL092024", "HELENE", ATCF_DIR / "aal092024.dat.gz", 2024),
    StormConfig("AL142024", "MILTON", ATCF_DIR / "aal142024.dat.gz", 2024),
]


def _strip_mcc_footer(mcc_bytes: bytes) -> bytes:
    """See build_michael_dataset.py -- same one-off footer cleanup, same
    reasoning: MCC.csv's trailing 'Grand Total' row is an export artifact,
    not a county, and must not reach normalize_fips()."""
    text = mcc_bytes.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    header, data_lines = lines[0], lines[1:]
    kept = [ln for ln in data_lines if ln.split(",", 1)[0].strip().isdigit()]
    return (header + "".join(kept)).encode("utf-8")


def _ensure_eaglei_year_cached(year: int) -> Path:
    local_path = EAGLEI_DIR / f"eaglei_outages_{year}.csv"
    if not local_path.exists():
        data = dataset.read_zip_member_from_gcs(EAGLEI_ZIP_REL_PATH, f"eaglei_outages_{year}.csv")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
    return local_path


def main() -> dict:
    # --- storm-independent inputs, loaded once and reused across all storms ---
    hurdat2_storms = parse_hurdat2_storms(HURDAT2_PATH)
    centroids = load_county_centroids(CENSUS_SHP_PATH)
    nri_df = dataset.load_nri_table()
    svi_df = dataset.load_svi_table()
    oni_df = dataset.load_oni_table()
    mcc_bytes = MCC_LOCAL_CACHE.read_bytes() if MCC_LOCAL_CACHE.exists() else dataset.read_zip_member_from_gcs(
        EAGLEI_ZIP_REL_PATH, "MCC.csv"
    )
    mcc_df = load_mcc_customers(io.BytesIO(_strip_mcc_footer(mcc_bytes)))
    fall2025_df = dataset.load_fall2025_customer_table()
    denominator_df = build_customer_denominator_table(fall2025_df, mcc_df)

    # one EAGLE-I annual file fetched/cached per distinct year, not per storm
    # (2018 covers Florence+Michael, 2024 covers Helene+Milton)
    years_needed = sorted({c.eaglei_year for c in STORM_CONFIGS})
    eaglei_paths = {year: _ensure_eaglei_year_cached(year) for year in years_needed}

    per_storm_diagnostics: dict[str, dict] = {}
    excluded_storms: list[dict] = []
    all_rows = []

    for config in STORM_CONFIGS:
        try:
            result = build_storm_dataset(
                storm_id=config.storm_id, storm_name=config.storm_name,
                hurdat2_storms=hurdat2_storms, atcf_path=config.atcf_path, centroids=centroids,
                nri_df=nri_df, svi_df=svi_df, oni_df=oni_df, mcc_df=mcc_df,
                denominator_df=denominator_df, eaglei_local_csv_path=eaglei_paths[config.eaglei_year],
            )
        except (RuntimeError, ValueError, FileNotFoundError) as e:
            excluded_storms.append({"storm_id": config.storm_id, "storm_name": config.storm_name, "reason": str(e)})
            continue

        per_storm_diagnostics[config.storm_id] = result.diagnostics
        for r in result.successes:
            all_rows.append({
                **r.to_feature_dict(),
                "pct_customers_out": r.pct_customers_out,
                "storm_id": r.storm_id,
                "storm_name": r.storm_name,
                "county_fips": r.county_fips,
                "lead_time_h": r.lead_time_h,
                "assumed_zero": r.assumed_zero,
                "wind_estimate_method": r.wind_estimate_method,
                "customers_out_peak": r.customers_out_peak,
                "customer_denominator": r.customer_denominator,
                "customer_denominator_source": r.customer_denominator_source,
                "impact_time_utc": r.impact_time_utc,
            })

    combined_df = pd.DataFrame(all_rows)

    # --- combined-dataset validation -----------------------------------------
    dup_keys = combined_df.duplicated(subset=["storm_id", "county_fips", "lead_time_h"])
    n_duplicate_keys = int(dup_keys.sum())

    feature_missingness = {col: int(combined_df[col].isnull().sum()) for col in FEATURE_COLUMNS}

    pct = combined_df["pct_customers_out"]
    combined_target_stats = {
        "min": float(pct.min()), "median": float(pct.median()), "mean": float(pct.mean()),
        "p90": float(pct.quantile(0.90)), "p95": float(pct.quantile(0.95)), "max": float(pct.max()),
    }

    rows_per_horizon = combined_df.groupby("lead_time_h").size().to_dict()
    rows_per_storm = combined_df.groupby("storm_id").size().to_dict()

    combined_diagnostics = {
        "total_storms_included": len(per_storm_diagnostics),
        "included_storm_ids": list(per_storm_diagnostics.keys()),
        "excluded_storms": excluded_storms,
        "unique_counties": int(combined_df["county_fips"].nunique()),
        "total_rows": len(combined_df),
        "rows_per_horizon": {str(k): int(v) for k, v in rows_per_horizon.items()},
        "rows_per_storm": rows_per_storm,
        "feature_missingness": feature_missingness,
        "target_distribution": combined_target_stats,
        "duplicate_key_count": n_duplicate_keys,
    }

    # --- leakage validation across every row ----------------------------------
    # build_storm_dataset() already asserts the leakage guard per row before a
    # row is ever added to successes; re-check it here too, independently,
    # across every storm's selected snapshots as the combined-dataset-level
    # validation the user asked for.
    leakage_violations = []
    leakage_ok = True
    for storm_id, diag in per_storm_diagnostics.items():
        for h_str, snap in diag["selected_snapshots"].items():
            cycle = pd.Timestamp(snap["cycle_init_time_utc"])
            impact = pd.Timestamp(diag["impact_time_utc"])
            lead_h = float(h_str)
            if not (cycle <= impact - pd.Timedelta(hours=lead_h)):
                leakage_ok = False
                leakage_violations.append({"storm_id": storm_id, "lead_time_h": lead_h})
    combined_diagnostics["leakage_validation_passed"] = leakage_ok
    combined_diagnostics["leakage_violations"] = leakage_violations

    # --- save artifacts (dev only, never committed) ---------------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    combined_df.to_csv(OUTPUT_DIR / "training_rows.csv", index=False)
    (OUTPUT_DIR / "per_storm_diagnostics.json").write_text(json.dumps(per_storm_diagnostics, indent=2, default=str))
    (OUTPUT_DIR / "combined_diagnostics.json").write_text(json.dumps(combined_diagnostics, indent=2, default=str))

    return per_storm_diagnostics, combined_diagnostics


if __name__ == "__main__":
    per_storm, combined = main()
    print(json.dumps({"per_storm": per_storm, "combined": combined}, indent=2, default=str))
