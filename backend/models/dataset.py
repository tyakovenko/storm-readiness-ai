"""Dataset preparation and static county feature loading with direct Google Cloud Storage support.

Loads and joins FEMA National Risk Index (NRI) and CDC Social Vulnerability Index (SVI)
by 5-digit county FIPS to provide real demographic, hazard, and vulnerability baselines.
Supports reading locally from data/raw/ or streaming directly from Google Cloud Storage
(gs://uc3-storm-impact-intelligence-data).
"""

from __future__ import annotations
import io
import logging
import os
from pathlib import Path
from typing import BinaryIO
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DATA_DIR = REPO_ROOT / "data"
DEFAULT_GCS_BUCKET = os.getenv("STORM_DATA_BUCKET", "uc3-storm-impact-intelligence-data")

NRI_PATH = LOCAL_DATA_DIR / "raw" / "nri" / "nri_counties.csv"
SVI_PATH = LOCAL_DATA_DIR / "raw" / "svi" / "SVI_2020_US_COUNTY.csv"
ONI_PATH = LOCAL_DATA_DIR / "raw" / "oni" / "oni.ascii.txt"


def get_gcs_blob_bytes(gcs_uri_or_path: str, bucket_name: str = DEFAULT_GCS_BUCKET) -> bytes:
    """Download blob bytes directly from Google Cloud Storage."""
    from google.cloud import storage

    client = storage.Client()
    if gcs_uri_or_path.startswith("gs://"):
        parts = gcs_uri_or_path[5:].split("/", 1)
        bucket = client.bucket(parts[0])
        blob_path = parts[1] if len(parts) > 1 else ""
    else:
        bucket = client.bucket(bucket_name)
        blob_path = gcs_uri_or_path.lstrip("/")

    blob = bucket.blob(blob_path)
    log.info(f"Streaming gs://{bucket.name}/{blob_path} directly from Google Cloud Storage...")
    return blob.download_as_bytes()


def load_dataframe_from_gcs_or_local(
    rel_path: str,
    usecols: list[str] | None = None,
    dtype: dict | None = None,
    prefer_gcs: bool = False,
) -> pd.DataFrame:
    """Load a DataFrame from local disk, or directly stream from GCS if local file is missing or prefer_gcs=True."""
    local_file = LOCAL_DATA_DIR / rel_path

    if prefer_gcs or not local_file.exists():
        try:
            raw_bytes = get_gcs_blob_bytes(rel_path)
            buf = io.BytesIO(raw_bytes)
            if rel_path.endswith(".parquet"):
                return pd.read_parquet(buf, columns=usecols)
            return pd.read_csv(buf, usecols=usecols, dtype=dtype)
        except Exception as e:
            if not local_file.exists():
                raise FileNotFoundError(f"Failed to load {rel_path} locally and from GCS: {e}")
            log.warning(f"GCS stream failed ({e}); falling back to local file {local_file}")

    if rel_path.endswith(".parquet"):
        return pd.read_parquet(local_file, columns=usecols)
    return pd.read_csv(local_file, usecols=usecols, dtype=dtype)


def load_county_static_lookup(prefer_gcs: bool = False) -> dict[str, dict]:
    """Load joined static county features (NRI + SVI + Demographics) indexed by 5-digit FIPS."""
    df_nri = load_dataframe_from_gcs_or_local(
        "raw/nri/nri_counties.csv",
        usecols=["STCOFIPS", "COUNTY", "STATEABBRV", "POPULATION", "HRCN_EALB", "HRCN_RISKS"],
        dtype={"STCOFIPS": str},
        prefer_gcs=prefer_gcs,
    )
    df_nri["fips"] = df_nri["STCOFIPS"].str.zfill(5)

    df_svi = load_dataframe_from_gcs_or_local(
        "raw/svi/SVI_2020_US_COUNTY.csv",
        usecols=["FIPS", "RPL_THEMES"],
        dtype={"FIPS": str},
        prefer_gcs=prefer_gcs,
    )
    df_svi["fips"] = df_svi["FIPS"].str.zfill(5)

    merged = pd.merge(df_nri, df_svi, on="fips", how="left")

    lookup = {}
    for _, row in merged.iterrows():
        fips = row["fips"]
        # Handle SVI missing or negative sentinel values (e.g. -999)
        svi_val = float(row["RPL_THEMES"]) if pd.notnull(row["RPL_THEMES"]) else 0.50
        if svi_val < 0.0 or svi_val > 1.0:
            svi_val = 0.50

        nri_risk = float(row["HRCN_RISKS"]) if pd.notnull(row["HRCN_RISKS"]) else 20.0
        nri_eal = float(row["HRCN_EALB"]) if pd.notnull(row["HRCN_EALB"]) else 100000.0
        pop = int(row["POPULATION"]) if pd.notnull(row["POPULATION"]) else 50000

        lookup[fips] = {
            "fips": fips,
            "name": f"{row['COUNTY']} County" if pd.notnull(row['COUNTY']) else "Unknown",
            "state": str(row["STATEABBRV"]) if pd.notnull(row["STATEABBRV"]) else "US",
            "population": pop,
            "customers_served": int(pop * 0.48),  # Standard utility rule-of-thumb: ~0.48 meters per capita
            "nri_risk_score": nri_risk,
            "nri_eal_building": nri_eal,
            "svi_overall": svi_val,
        }
    return lookup


def get_latest_oni_anomaly(prefer_gcs: bool = False) -> float:
    """Read the latest ONI (Oceanic Niño Index) anomaly value from local file or GCS."""
    try:
        if prefer_gcs or not ONI_PATH.exists():
            data = get_gcs_blob_bytes("raw/oni/oni.ascii.txt").decode("utf-8")
        else:
            with open(ONI_PATH, "r") as f:
                data = f.read()

        lines = [line.strip() for line in data.splitlines() if line.strip() and not line.startswith("SEAS")]
        if lines:
            last_line = lines[-1].split()
            # Line format: SEAS YR TOTAL ANOM
            return float(last_line[3])
    except Exception as e:
        log.warning(f"Failed to parse ONI: {e}")
    return 0.0
