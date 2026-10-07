"""Historical outage target construction: EAGLE-I outages + a county customer-
count denominator -> pct_customers_out.

(see docs/data-contract.md's target definition: peak % customers out = max
EAGLE-I customers_out / total customers served). This module only builds the
target for a given, already-decided time window; it does not choose that
window (ATCF/HURDAT processing does, elsewhere) and does not join ATCF/NRI/
SVI/ONI.

Canonical denominator (Phase 3K, superseding the MCC-only approach): the
Fall-2025 EAGLE-I county customer dataset
(raw/census/EAGLE I/eaglei_county_customers_fall_2025.csv, loaded via
dataset.load_fall2025_customer_table()). Phase 3J found it has a median 1.68%
absolute error against the 2024 EAGLE-I embedded total_customers benchmark
with no systematic bias, vs the archive-bundled MCC.csv's 17.31% median error
and a systematic ~-14.5% undercount -- the undercount is what caused Michael
2018's implausible >100% raw ratios for small Georgia counties (Phase 3H/3I).
MCC.csv is kept only as an explicit, narrowly-scoped fallback for counties
Fall-2025 doesn't cover (see build_customer_denominator_table() and
FALL2025_KNOWN_GAP_FIPS below) -- never a silent backfill for an arbitrary
missing county.

KNOWN LIMITATION carried over from dataset.load_fall2025_customer_table():
Fall-2025 is a single static snapshot (2023 EIA-861 + 2021 HIFLD + 2021
LandScan) applied retrospectively to every historical storm year regardless
of that storm's actual year. Documented, not silently hidden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO

import pandas as pd

EAGLEI_REQUIRED_COLUMNS = ["fips_code", "county", "state", "customers_out", "run_start_time"]
MCC_REQUIRED_COLUMNS = ["County_FIPS", "Customers"]


def normalize_fips(value: str | int | float) -> str:
    """Zero-pad a county FIPS code to a 5-character string.

    Pandas often infers fips_code/County_FIPS as int64, which silently drops
    the leading zero (e.g. 1001 instead of "01001") and breaks joins against
    NRI/SVI. Always normalize through this function before joining or
    comparing FIPS codes.
    """
    if value is None:
        raise ValueError("FIPS code cannot be None")
    text = str(value).strip()
    if text.endswith(".0"):  # a float-typed column (e.g. "1001.0") read via pandas
        text = text[:-2]
    if not text.isdigit():
        raise ValueError(f"FIPS code is not numeric: {value!r}")
    if len(text) > 5:
        raise ValueError(f"FIPS code has more than 5 digits: {value!r}")
    return text.zfill(5)


def _process_eaglei_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """Shared row-processing for one EAGLE-I DataFrame (a full file or one
    chunksize-row chunk of one): required-column check, fips normalization,
    dtype casts. Used by both load_eaglei_outages() and
    load_eaglei_outages_filtered() so they can't silently drift apart.

    Some archive years (confirmed: 2023's eaglei_outages_2023.csv inside
    24237376.zip) name the customers-out column "sum" instead of
    "customers_out" -- the same quantity ORNL's own bundled Uri_Map.R script
    (Phase 3H) refers to as "sum" for its 2021 file. Normalize that one
    known rename here rather than failing a storm whose data is otherwise
    fine; this is not a value change, just reading it under its real name.
    """
    if "customers_out" not in df.columns and "sum" in df.columns:
        df = df.rename(columns={"sum": "customers_out"})

    missing = [c for c in EAGLEI_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"EAGLE-I file is missing required columns: {missing}")

    df = df[EAGLEI_REQUIRED_COLUMNS].copy()
    df["county_fips"] = df["fips_code"].map(normalize_fips)
    df["customers_out"] = df["customers_out"].astype(float)
    df["run_start_time"] = pd.to_datetime(df["run_start_time"])
    return df[["county_fips", "county", "state", "customers_out", "run_start_time"]]


def load_eaglei_outages(source: str | Path | IO) -> pd.DataFrame:
    """Load one EAGLE-I outages CSV (one storm-year file from 24237376.zip)
    in full.

    Returns columns: county_fips (normalized), county, state, customers_out
    (float), run_start_time (datetime64). For a large annual file where only
    a narrow time window and/or county set is actually needed, prefer
    load_eaglei_outages_filtered() -- this function holds the entire file in
    memory as one DataFrame.
    """
    df = pd.read_csv(source, dtype={"fips_code": str})
    return _process_eaglei_chunk(df)


def load_eaglei_outages_filtered(
    source: str | Path,
    window_start: datetime,
    window_end: datetime,
    candidate_fips: set[str] | None = None,
    chunksize: int = 2_000_000,
) -> pd.DataFrame:
    """Chunked variant of load_eaglei_outages() for large annual files
    (Phase 3L: a full year is ~20-30M rows / ~1-1.5GB).

    Reads `source` in chunksize-row chunks and keeps only rows within
    [window_start, window_end] and (if given) whose county_fips is in
    candidate_fips, concatenating just the kept rows -- an entire annual
    file's rows are never all held in memory at once, only one chunk plus
    the (much smaller) accumulated matches. Same output shape/dtypes as
    load_eaglei_outages(); shares _process_eaglei_chunk() so the two can't
    silently diverge in semantics.

    `source` must be a local path, not an in-memory buffer -- pandas
    re-reads it in chunks via its own file handle, which only pays off
    against a real seekable file, not bytes already fully loaded into memory.
    """
    kept_chunks = []
    for raw_chunk in pd.read_csv(source, dtype={"fips_code": str}, chunksize=chunksize):
        chunk = _process_eaglei_chunk(raw_chunk)
        mask = (chunk["run_start_time"] >= window_start) & (chunk["run_start_time"] <= window_end)
        if candidate_fips is not None:
            mask &= chunk["county_fips"].isin(candidate_fips)
        if mask.any():
            kept_chunks.append(chunk.loc[mask])

    if not kept_chunks:
        return pd.DataFrame(columns=["county_fips", "county", "state", "customers_out", "run_start_time"])
    return pd.concat(kept_chunks, ignore_index=True)


def load_mcc_customers(source: str | Path | IO) -> pd.DataFrame:
    """Load the archive-bundled MCC.csv (historical customer-count denominator).

    Returns columns: county_fips (normalized), mcc_customers (float).
    """
    df = pd.read_csv(source, dtype={"County_FIPS": str})
    missing = [c for c in MCC_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"MCC file is missing required columns: {missing}")

    df = df[MCC_REQUIRED_COLUMNS].copy()
    df["county_fips"] = df["County_FIPS"].map(normalize_fips)
    df["mcc_customers"] = df["Customers"].astype(float)
    return df[["county_fips", "mcc_customers"]]


def peak_customers_out(
    outages_df: pd.DataFrame,
    county_fips: str,
    window_start: datetime,
    window_end: datetime,
) -> tuple[float, bool]:
    """Peak customers_out for one county within [window_start, window_end].

    Returns (peak, assumed_zero). assumed_zero=True means no EAGLE-I rows
    were found for this county in this window, and the peak was set to 0.0
    through this explicit path -- NOT verified against coverage data.

    EAGLE-I's own documentation states rows with customers_out == 0 are
    omitted from the file entirely, not recorded as zero. So "no rows in
    window" is genuinely ambiguous: it could mean a true zero-outage window,
    or a monitoring gap where EAGLE-I had no coverage for that county/utility
    at the time. coverage_history.csv (state-year EAGLE-I coverage, found
    inside 24237376.zip) is NOT joined in yet, so this function cannot tell
    the two apart. Treat every assumed_zero=True result as provisional until
    a later phase cross-checks it against coverage_history.csv.
    """
    fips = normalize_fips(county_fips)
    in_window = (outages_df["run_start_time"] >= window_start) & (
        outages_df["run_start_time"] <= window_end
    )
    rows = outages_df.loc[(outages_df["county_fips"] == fips) & in_window]
    if rows.empty:
        return 0.0, True
    return float(rows["customers_out"].max()), False


def compute_pct_customers_out(customers_out_peak: float, customer_denominator: float) -> float:
    """100 * customers_out_peak / customer_denominator, clipped to [0, 100].

    Raises ValueError on a non-positive, missing, or NaN denominator, and on
    a negative peak -- these indicate a bad join or bad input data, not a
    real 0% outage, so they must not silently produce a wrong percentage.
    Clipping above 100 is expected and intentional (see module docstring):
    even the better Fall-2025 denominator is a modeled approximation, and
    ORNL's own reference usage of the EAGLE-I data clips the same way.
    """
    if customers_out_peak < 0:
        raise ValueError(f"customers_out_peak cannot be negative: {customers_out_peak!r}")
    if customer_denominator is None or (isinstance(customer_denominator, float) and math.isnan(customer_denominator)):
        raise ValueError(f"customer_denominator is missing: {customer_denominator!r}")
    if customer_denominator <= 0:
        raise ValueError(f"customer_denominator must be > 0, got {customer_denominator!r}")

    pct = 100.0 * customers_out_peak / customer_denominator
    return min(100.0, max(0.0, pct))


# Fall-2025 reports Connecticut under post-2022 planning-region FIPS instead
# of these 8 legacy county FIPS (confirmed in Phase 3J against the 2024
# EAGLE-I benchmark, which -- like MCC.csv -- still uses the legacy codes).
# This is the ONLY fallback case build_customer_denominator_table() supports;
# any other county missing from Fall-2025 is left out of the table on
# purpose, so compute_county_outage_target() fails loudly for it rather than
# silently reaching for MCC.
FALL2025_KNOWN_GAP_FIPS = frozenset({
    "09001", "09003", "09005", "09007", "09009", "09011", "09013", "09015",
})


def build_customer_denominator_table(
    fall2025_df: pd.DataFrame,
    mcc_df: pd.DataFrame,
) -> pd.DataFrame:
    """Unified customer-count denominator: Fall-2025 primarily, with MCC.csv
    as an explicit fallback restricted to FALL2025_KNOWN_GAP_FIPS.

    Returns columns: county_fips, customer_denominator, customer_denominator_source
    ("fall2025" or "mcc_fallback"). A county fips not present in the result
    has no supported denominator and must not be silently invented --
    compute_county_outage_target() raises for it.
    """
    primary = fall2025_df[["county_fips", "customers"]].rename(columns={"customers": "customer_denominator"})
    primary["customer_denominator_source"] = "fall2025"

    fallback = mcc_df.loc[mcc_df["county_fips"].isin(FALL2025_KNOWN_GAP_FIPS)].copy()
    fallback = fallback.rename(columns={"mcc_customers": "customer_denominator"})
    fallback["customer_denominator_source"] = "mcc_fallback"
    # Defensive: if a "known gap" fips is actually present in Fall-2025 after
    # all (e.g. a future Fall-2025 release adds it back), prefer that over MCC.
    fallback = fallback.loc[~fallback["county_fips"].isin(primary["county_fips"])]

    return pd.concat([primary, fallback], ignore_index=True)[
        ["county_fips", "customer_denominator", "customer_denominator_source"]
    ]


@dataclass(frozen=True)
class CountyOutageTarget:
    county_fips: str
    window_start: datetime
    window_end: datetime
    customers_out_peak: float
    customer_denominator: float
    customer_denominator_source: str
    pct_customers_out: float
    assumed_zero: bool  # see peak_customers_out()


def compute_county_outage_target(
    outages_df: pd.DataFrame,
    denominator_df: pd.DataFrame,
    county_fips: str,
    window_start: datetime,
    window_end: datetime,
) -> CountyOutageTarget:
    """Full target for one (county, window): resolve the denominator, find
    the peak, compute pct.

    denominator_df is the already-unified table from
    build_customer_denominator_table() -- this function does not know or
    care whether a given county's value came from Fall-2025 or the MCC
    fallback, it just looks it up and records the source in provenance.

    window_start/window_end are required inputs, not decided here -- the
    ATCF/HURDAT processing determines the storm window for each lead-time
    snapshot, elsewhere.
    """
    fips = normalize_fips(county_fips)
    row = denominator_df.loc[denominator_df["county_fips"] == fips]
    if row.empty:
        raise ValueError(
            f"No customer denominator found for county {fips}: not present in the "
            f"Fall-2025 dataset and not a recognized MCC-fallback case "
            f"(see FALL2025_KNOWN_GAP_FIPS)"
        )

    customer_denominator = float(row["customer_denominator"].iloc[0])
    customer_denominator_source = str(row["customer_denominator_source"].iloc[0])
    peak, assumed_zero = peak_customers_out(outages_df, fips, window_start, window_end)
    pct = compute_pct_customers_out(peak, customer_denominator)

    return CountyOutageTarget(
        county_fips=fips,
        window_start=window_start,
        window_end=window_end,
        customers_out_peak=peak,
        customer_denominator=customer_denominator,
        customer_denominator_source=customer_denominator_source,
        pct_customers_out=pct,
        assumed_zero=assumed_zero,
    )
