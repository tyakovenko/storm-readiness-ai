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
import zipfile
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
FALL2025_CUSTOMERS_PATH = LOCAL_DATA_DIR / "raw" / "census" / "EAGLE I" / "eaglei_county_customers_fall_2025.csv"


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


def load_nri_table(prefer_gcs: bool = False) -> pd.DataFrame:
    """Raw NRI county rows (STCOFIPS, POPULATION, HRCN_EALB, HRCN_RISKS) with a
    normalized 5-char fips column added. Unlike load_county_static_lookup(), this
    does not fill in defaults for missing/sentinel values -- callers building
    training data (county_context_features.py) need to see real gaps, not the
    stub-safe defaults load_county_static_lookup() uses for the live demo."""
    df = load_dataframe_from_gcs_or_local(
        "raw/nri/nri_counties.csv",
        usecols=["STCOFIPS", "POPULATION", "HRCN_EALB", "HRCN_RISKS"],
        dtype={"STCOFIPS": str},
        prefer_gcs=prefer_gcs,
    )
    df["fips"] = df["STCOFIPS"].str.zfill(5)
    return df


def load_svi_table(prefer_gcs: bool = False) -> pd.DataFrame:
    """Raw SVI county rows (FIPS, RPL_THEMES) with a normalized 5-char fips column
    added. See load_nri_table()'s docstring -- no default-filling here."""
    df = load_dataframe_from_gcs_or_local(
        "raw/svi/SVI_2020_US_COUNTY.csv",
        usecols=["FIPS", "RPL_THEMES"],
        dtype={"FIPS": str},
        prefer_gcs=prefer_gcs,
    )
    df["fips"] = df["FIPS"].str.zfill(5)
    return df


def load_oni_table(prefer_gcs: bool = False) -> pd.DataFrame:
    """Full ONI ascii table as (season, year, anom) rows, one per 3-month rolling
    season. See get_latest_oni_anomaly() for the single-latest-value variant the
    live pipeline uses; this variant is for matching a specific storm/snapshot
    date to its season (county_context_features.py), so it needs every row."""
    if prefer_gcs or not ONI_PATH.exists():
        data = get_gcs_blob_bytes("raw/oni/oni.ascii.txt").decode("utf-8")
    else:
        with open(ONI_PATH, "r") as f:
            data = f.read()

    rows = []
    for line in data.splitlines():
        line = line.strip()
        if not line or line.startswith("SEAS"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        rows.append({"season": parts[0], "year": int(parts[1]), "anom": float(parts[3])})
    return pd.DataFrame(rows, columns=["season", "year", "anom"])


def load_fall2025_customer_table(prefer_gcs: bool = False) -> pd.DataFrame:
    """The Fall-2025 EAGLE-I county customer dataset -- the canonical customer-
    count denominator for historical outage-target construction (see Phase
    3J: median 1.68% abs error vs the 2024 EAGLE-I embedded total_customers
    benchmark, with no systematic bias, vs MCC.csv's 17.31% median error and
    a systematic ~-14.5% undercount). outage_target.py's
    build_customer_denominator_table() uses this as the primary source, with
    MCC.csv as an explicit, narrowly-scoped fallback only for Fall-2025's
    known gaps (currently Connecticut's legacy county FIPS).

    KNOWN LIMITATION: this is a single static snapshot modeled from 2023
    EIA-861 + 2021 HIFLD + 2021 LandScan inputs (per its own README) and does
    not vary by year -- it is applied retrospectively to every historical
    storm year (2014-2025) regardless of that storm's actual year. Accepted
    as a documented limitation (see Phase 3J), not silently hidden.

    Returns columns: county_fips (normalized), customers.
    """
    df = load_dataframe_from_gcs_or_local(
        "raw/census/EAGLE I/eaglei_county_customers_fall_2025.csv",
        usecols=["county_fips", "customers"],
        dtype={"county_fips": str},
        prefer_gcs=prefer_gcs,
    )
    df["county_fips"] = df["county_fips"].str.zfill(5)
    return df


class _GCSRangeReader(io.RawIOBase):
    """Seekable, read-only file-like view over a GCS blob where every read
    issues an HTTP byte-range GET instead of transferring the whole object.

    Lets zipfile.ZipFile parse a remote archive's end-of-central-directory
    and central directory (seeking around near the end of the file) and then
    extract one member's data, touching only the bytes those operations
    actually need -- critical for the 11.6GB EAGLE-I historical archive
    (24237376.zip), where only one year's outage csv + MCC.csv are ever
    needed. `size` must be passed in (from a metadata-only call) since
    reading it from the stream would defeat the point."""

    def __init__(self, blob, size: int):
        self._blob = blob
        self._size = size
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        elif whence == io.SEEK_END:
            self._pos = self._size + offset
        else:
            raise ValueError(f"unsupported whence: {whence}")
        return self._pos

    def readinto(self, b) -> int:
        if self._pos >= self._size:
            return 0
        end = min(self._pos + len(b), self._size) - 1  # GCS range end is inclusive
        data = self._blob.download_as_bytes(start=self._pos, end=end)
        n = len(data)
        b[:n] = data
        self._pos += n
        return n


def _get_gcs_blob(rel_path: str, bucket_name: str = DEFAULT_GCS_BUCKET):
    """A GCS Blob with metadata (incl. size) already loaded, via a metadata-only
    call -- bucket.get_blob() does not transfer the object's content."""
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.get_blob(rel_path)
    if blob is None:
        raise FileNotFoundError(f"gs://{bucket_name}/{rel_path} not found")
    return blob


def list_zip_members_from_gcs(rel_path: str, bucket_name: str = DEFAULT_GCS_BUCKET) -> list[str]:
    """Member names of a zip archive on GCS, read via byte-range requests
    against its central directory only -- never the archive's full content."""
    blob = _get_gcs_blob(rel_path, bucket_name)
    with zipfile.ZipFile(_GCSRangeReader(blob, blob.size)) as zf:
        return zf.namelist()


def read_zip_member_from_gcs(rel_path: str, member_name: str, bucket_name: str = DEFAULT_GCS_BUCKET) -> bytes:
    """Bytes of one member of a zip archive on GCS, via byte-range requests
    for its central-directory entry and its own data region only."""
    blob = _get_gcs_blob(rel_path, bucket_name)
    with zipfile.ZipFile(_GCSRangeReader(blob, blob.size)) as zf:
        return zf.read(member_name)
