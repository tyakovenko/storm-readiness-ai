"""Phase 3G/3K: build the real-data Hurricane Michael (AL142018) training
dataset. Thin wrapper around storm_pipeline.build_storm_dataset() (Phase 3L
factored this storm's original orchestration logic out into that shared,
reusable function) -- kept so this storm can still be run/inspected on its
own, byte-identical to before the refactor.

Run from the backend/ directory: PYTHONPATH=.. ./.venv/Scripts/python.exe scripts/build_michael_dataset.py
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd

from backend.models import dataset
from backend.models.hurdat2 import parse_hurdat2_storms
from backend.models.outage_target import build_customer_denominator_table, load_eaglei_outages, load_mcc_customers
from backend.scripts.storm_pipeline import build_storm_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

STORM_ID = "AL142018"
STORM_NAME = "MICHAEL"
HURDAT2_PATH = DATA_DIR / "raw" / "hurdat2" / "hurdat2_atlantic.txt"
ATCF_PATH = DATA_DIR / "raw" / "national" / "atcf_archive_2014_2025" / "aal142018.dat.gz"
CENSUS_SHP_PATH = DATA_DIR / "raw" / "census" / "counties" / "cb_2025_us_county_500k.shp"

EAGLEI_ZIP_REL_PATH = "raw/census/EAGLE I/24237376.zip"
EAGLEI_2018_MEMBER = "eaglei_outages_2018.csv"
MCC_MEMBER = "MCC.csv"
MCC_LOCAL_CACHE = DATA_DIR / "raw" / "census" / "EAGLE I" / "MCC.csv"
EAGLEI_2018_LOCAL_CACHE = DATA_DIR / "raw" / "census" / "EAGLE I" / "eaglei_outages_2018.csv"

OUTPUT_DIR = DATA_DIR / "processed" / "michael_2018"


def _strip_mcc_footer(mcc_bytes: bytes) -> bytes:
    """Real MCC.csv has a trailing 'Grand Total' summary row (an export
    artifact, not a county) that breaks normalize_fips(). Drop any row whose
    first field isn't purely numeric before handing off to
    outage_target.load_mcc_customers(), which should stay strict/loud for
    genuine bad FIPS data -- this is footer cleanup for one file's export
    format, not a change to that contract."""
    text = mcc_bytes.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    header, data_lines = lines[0], lines[1:]
    kept = [ln for ln in data_lines if ln.split(",", 1)[0].strip().isdigit()]
    return (header + "".join(kept)).encode("utf-8")


def _load_eaglei_zip_member(member_name: str, local_cache: Path) -> bytes:
    """Local cache first; otherwise a selective byte-range read of just this
    member from the 11.6GB archive (dataset.read_zip_member_from_gcs) -- the
    full archive is never downloaded either way."""
    if local_cache.exists():
        return local_cache.read_bytes()
    data = dataset.read_zip_member_from_gcs(EAGLEI_ZIP_REL_PATH, member_name)
    local_cache.parent.mkdir(parents=True, exist_ok=True)
    local_cache.write_bytes(data)
    return data


def main() -> dict:
    from backend.models.county_geometry import load_county_centroids

    storms = parse_hurdat2_storms(HURDAT2_PATH)
    centroids = load_county_centroids(CENSUS_SHP_PATH)

    nri_df = dataset.load_nri_table()
    svi_df = dataset.load_svi_table()
    oni_df = dataset.load_oni_table()
    mcc_df = load_mcc_customers(io.BytesIO(
        _strip_mcc_footer(_load_eaglei_zip_member(MCC_MEMBER, MCC_LOCAL_CACHE))
    ))
    fall2025_df = dataset.load_fall2025_customer_table()
    denominator_df = build_customer_denominator_table(fall2025_df, mcc_df)

    # ensure the 2018 member is cached locally (load_eaglei_outages_filtered
    # needs a real local path, not an in-memory buffer -- see its docstring)
    if not EAGLEI_2018_LOCAL_CACHE.exists():
        data = _load_eaglei_zip_member(EAGLEI_2018_MEMBER, EAGLEI_2018_LOCAL_CACHE)

    result = build_storm_dataset(
        storm_id=STORM_ID, storm_name=STORM_NAME,
        hurdat2_storms=storms, atcf_path=ATCF_PATH, centroids=centroids,
        nri_df=nri_df, svi_df=svi_df, oni_df=oni_df, mcc_df=mcc_df,
        denominator_df=denominator_df, eaglei_local_csv_path=EAGLEI_2018_LOCAL_CACHE,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows_df = pd.DataFrame([
        {
            **r.to_feature_dict(),
            "pct_customers_out": r.pct_customers_out,
            "county_fips": r.county_fips,
            "lead_time_h": r.lead_time_h,
            "assumed_zero": r.assumed_zero,
            "wind_estimate_method": r.wind_estimate_method,
            "customers_out_peak": r.customers_out_peak,
            "customer_denominator": r.customer_denominator,
            "customer_denominator_source": r.customer_denominator_source,
        }
        for r in result.successes
    ])
    rows_df.to_csv(OUTPUT_DIR / "training_rows.csv", index=False)
    (OUTPUT_DIR / "diagnostics.json").write_text(json.dumps(result.diagnostics, indent=2, default=str))

    return result.diagnostics, result.successes


if __name__ == "__main__":
    diag, _rows = main()
    print(json.dumps(diag, indent=2, default=str))
