"""Tests for historical outage target construction.
Uses small synthetic EAGLE-I/MCC samples only -- no real archive data.
"""

import io
import math
from datetime import datetime

import pandas as pd
import pytest

from backend.models.outage_target import (
    FALL2025_KNOWN_GAP_FIPS,
    CountyOutageTarget,
    build_customer_denominator_table,
    compute_county_outage_target,
    compute_pct_customers_out,
    load_eaglei_outages,
    load_eaglei_outages_filtered,
    load_mcc_customers,
    normalize_fips,
    peak_customers_out,
)

EAGLEI_SAMPLE = """fips_code,county,state,customers_out,run_start_time
12075,Levy,Florida,100,2018-10-10 00:00:00
12075,Levy,Florida,500,2018-10-10 06:00:00
12075,Levy,Florida,300,2018-10-10 12:00:00
12075,Levy,Florida,50,2018-10-15 00:00:00
12029,Dixie,Florida,80,2018-10-10 06:00:00
"""

MCC_SAMPLE = """County_FIPS,Customers
12075,1000
12029,500
12017,0
12123,2000
"""

FALL2025_SAMPLE = pd.DataFrame([
    {"county_fips": "12075", "customers": 1050.0},
    {"county_fips": "12029", "customers": 520.0},
])


def _denominator_df_from_mcc(mcc_df: pd.DataFrame) -> pd.DataFrame:
    """compute_county_outage_target() tests below exercise target logic
    (peak/window/clipping), not denominator-source resolution policy (that
    has its own dedicated tests for build_customer_denominator_table()) --
    so just reshape an mcc_df into the unified denominator_df shape directly."""
    df = mcc_df.rename(columns={"mcc_customers": "customer_denominator"}).copy()
    df["customer_denominator_source"] = "mcc_test"
    return df


# --- normalize_fips ---------------------------------------------------------


def test_normalize_fips_pads_short_codes():
    assert normalize_fips(1001) == "01001"
    assert normalize_fips("1001") == "01001"


def test_normalize_fips_leaves_full_length_codes():
    assert normalize_fips("12075") == "12075"


def test_normalize_fips_handles_pandas_float_rendering():
    # pandas can render an int-typed FIPS column as "1001.0" after a round trip
    assert normalize_fips("1001.0") == "01001"


def test_normalize_fips_rejects_non_numeric():
    with pytest.raises(ValueError):
        normalize_fips("abcde")


def test_normalize_fips_rejects_too_long():
    with pytest.raises(ValueError):
        normalize_fips("123456")


def test_normalize_fips_rejects_none():
    with pytest.raises(ValueError):
        normalize_fips(None)


# --- loaders -----------------------------------------------------------------


def test_load_eaglei_outages_normalizes_and_types():
    df = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    assert list(df.columns) == ["county_fips", "county", "state", "customers_out", "run_start_time"]
    assert set(df["county_fips"]) == {"12075", "12029"}
    assert df["customers_out"].dtype == float
    assert pd.api.types.is_datetime64_any_dtype(df["run_start_time"])


def test_load_eaglei_outages_missing_column_raises():
    bad_csv = "fips_code,county,state,customers_out\n12075,Levy,Florida,100\n"
    with pytest.raises(ValueError, match="missing required columns"):
        load_eaglei_outages(io.StringIO(bad_csv))


def test_load_eaglei_outages_accepts_sum_column_alias():
    # confirmed: the archive's 2023 file names this column "sum" instead of
    # "customers_out" (Phase 3L) -- same quantity, different historical name
    sum_csv = "fips_code,county,state,sum,run_start_time\n12075,Levy,Florida,100,2018-10-10 00:00:00\n"
    df = load_eaglei_outages(io.StringIO(sum_csv))
    assert df.loc[0, "customers_out"] == 100.0


# --- load_eaglei_outages_filtered (Phase 3L chunked/memory-bounded loader) -----


def test_load_eaglei_outages_filtered_matches_full_loader_within_window(tmp_path):
    path = tmp_path / "eaglei.csv"
    path.write_text(EAGLEI_SAMPLE)
    full = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    full_in_window = full[
        (full.run_start_time >= datetime(2018, 10, 10, 0, 0)) & (full.run_start_time <= datetime(2018, 10, 10, 23, 59))
    ].reset_index(drop=True)

    filtered = load_eaglei_outages_filtered(
        path, datetime(2018, 10, 10, 0, 0), datetime(2018, 10, 10, 23, 59), chunksize=2,
    ).sort_values("run_start_time").reset_index(drop=True)

    pd.testing.assert_frame_equal(filtered, full_in_window.sort_values("run_start_time").reset_index(drop=True))


def test_load_eaglei_outages_filtered_respects_candidate_fips(tmp_path):
    path = tmp_path / "eaglei.csv"
    path.write_text(EAGLEI_SAMPLE)
    filtered = load_eaglei_outages_filtered(
        path, datetime(2018, 10, 1), datetime(2018, 10, 31),
        candidate_fips={"12075"}, chunksize=2,
    )
    assert set(filtered["county_fips"]) == {"12075"}  # 12029 excluded even though in-window


def test_load_eaglei_outages_filtered_empty_result_has_correct_columns(tmp_path):
    path = tmp_path / "eaglei.csv"
    path.write_text(EAGLEI_SAMPLE)
    filtered = load_eaglei_outages_filtered(
        path, datetime(2000, 1, 1), datetime(2000, 1, 2), chunksize=2,
    )
    assert len(filtered) == 0
    assert list(filtered.columns) == ["county_fips", "county", "state", "customers_out", "run_start_time"]


def test_load_eaglei_outages_filtered_chunk_boundary_does_not_drop_matches(tmp_path):
    # chunksize=1 forces every row into its own chunk -- a correctness check
    # that filtering-per-chunk doesn't miss rows at arbitrary chunk boundaries
    path = tmp_path / "eaglei.csv"
    path.write_text(EAGLEI_SAMPLE)
    filtered = load_eaglei_outages_filtered(
        path, datetime(2018, 10, 10, 0, 0), datetime(2018, 10, 10, 23, 59), chunksize=1,
    )
    assert len(filtered) == 4  # the 4 EAGLEI_SAMPLE rows on 2018-10-10 (3 for 12075, 1 for 12029)


def test_load_mcc_customers_normalizes_and_types():
    df = load_mcc_customers(io.StringIO(MCC_SAMPLE))
    assert list(df.columns) == ["county_fips", "mcc_customers"]
    assert set(df["county_fips"]) == {"12075", "12029", "12017", "12123"}
    assert df["mcc_customers"].dtype == float


def test_load_mcc_customers_missing_column_raises():
    bad_csv = "County_FIPS\n12075\n"
    with pytest.raises(ValueError, match="missing required columns"):
        load_mcc_customers(io.StringIO(bad_csv))


# --- peak_customers_out -------------------------------------------------------


def test_peak_customers_out_picks_max_within_window():
    df = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    peak, assumed_zero = peak_customers_out(
        df, "12075", datetime(2018, 10, 10, 0, 0), datetime(2018, 10, 10, 23, 59)
    )
    assert peak == 500.0
    assert assumed_zero is False


def test_peak_customers_out_excludes_rows_outside_window():
    df = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    # window ends before the 500-customer spike on the 10th
    peak, assumed_zero = peak_customers_out(
        df, "12075", datetime(2018, 10, 10, 0, 0), datetime(2018, 10, 10, 1, 0)
    )
    assert peak == 100.0
    assert assumed_zero is False


def test_peak_customers_out_assumes_zero_when_no_rows():
    df = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    # 12017 has no rows in the sample at all
    peak, assumed_zero = peak_customers_out(
        df, "12017", datetime(2018, 10, 10, 0, 0), datetime(2018, 10, 11, 0, 0)
    )
    assert peak == 0.0
    assert assumed_zero is True


def test_peak_customers_out_normalizes_input_fips():
    df = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    peak, _ = peak_customers_out(df, 12075, datetime(2018, 10, 10), datetime(2018, 10, 11))
    assert peak == 500.0


# --- compute_pct_customers_out -------------------------------------------------


def test_compute_pct_customers_out_basic():
    assert compute_pct_customers_out(50.0, 200.0) == 25.0


def test_compute_pct_customers_out_clips_above_100():
    # a county can exceed its MCC estimate (modeled denominators are approximate);
    # the target must still clip to a valid percentage
    assert compute_pct_customers_out(300.0, 200.0) == 100.0


def test_compute_pct_customers_out_negative_peak_raises():
    with pytest.raises(ValueError):
        compute_pct_customers_out(-10.0, 200.0)


@pytest.mark.parametrize("bad_denominator", [0.0, -5.0, None, float("nan")])
def test_compute_pct_customers_out_invalid_denominator_raises(bad_denominator):
    with pytest.raises(ValueError):
        compute_pct_customers_out(50.0, bad_denominator)


# --- compute_county_outage_target (full join) ----------------------------------


def test_compute_county_outage_target_happy_path():
    outages = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    mcc = load_mcc_customers(io.StringIO(MCC_SAMPLE))
    denominator_df = _denominator_df_from_mcc(mcc)
    result = compute_county_outage_target(
        outages, denominator_df, "12075", datetime(2018, 10, 10, 0, 0), datetime(2018, 10, 10, 23, 59)
    )
    assert isinstance(result, CountyOutageTarget)
    assert result.county_fips == "12075"
    assert result.customers_out_peak == 500.0
    assert result.customer_denominator == 1000.0
    assert result.customer_denominator_source == "mcc_test"
    assert result.pct_customers_out == 50.0
    assert result.assumed_zero is False


def test_compute_county_outage_target_assumed_zero_path():
    outages = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    mcc = load_mcc_customers(io.StringIO(MCC_SAMPLE))
    denominator_df = _denominator_df_from_mcc(mcc)
    # 12123 has a valid denominator but no EAGLE-I rows at all in the sample
    result = compute_county_outage_target(
        outages, denominator_df, "12123", datetime(2018, 10, 10), datetime(2018, 10, 11)
    )
    assert result.customers_out_peak == 0.0
    assert result.pct_customers_out == 0.0
    assert result.assumed_zero is True


def test_compute_county_outage_target_missing_denominator_county_raises():
    outages = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    mcc = load_mcc_customers(io.StringIO(MCC_SAMPLE))
    denominator_df = _denominator_df_from_mcc(mcc)
    with pytest.raises(ValueError, match="No customer denominator found"):
        compute_county_outage_target(outages, denominator_df, "99999", datetime(2018, 10, 10), datetime(2018, 10, 11))


def test_compute_county_outage_target_invalid_denominator_raises():
    outages = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    mcc = load_mcc_customers(io.StringIO(MCC_SAMPLE))
    denominator_df = _denominator_df_from_mcc(mcc)
    # 12017 is present but with Customers=0 -- must raise, not divide by zero
    with pytest.raises(ValueError, match="customer_denominator"):
        compute_county_outage_target(outages, denominator_df, "12017", datetime(2018, 10, 10), datetime(2018, 10, 11))


# --- build_customer_denominator_table (Phase 3K) -------------------------------


def test_denominator_table_prefers_fall2025_when_present():
    mcc = load_mcc_customers(io.StringIO(MCC_SAMPLE))
    table = build_customer_denominator_table(FALL2025_SAMPLE, mcc)
    row = table.loc[table.county_fips == "12075"].iloc[0]
    assert row.customer_denominator == 1050.0  # Fall-2025 value, not MCC's 1000.0
    assert row.customer_denominator_source == "fall2025"


def test_denominator_table_falls_back_to_mcc_for_known_gap_fips():
    ct_fips = next(iter(FALL2025_KNOWN_GAP_FIPS))
    mcc = load_mcc_customers(io.StringIO(f"County_FIPS,Customers\n{ct_fips},777\n"))
    table = build_customer_denominator_table(FALL2025_SAMPLE, mcc)
    row = table.loc[table.county_fips == ct_fips].iloc[0]
    assert row.customer_denominator == 777.0
    assert row.customer_denominator_source == "mcc_fallback"


def test_denominator_table_excludes_unsupported_gap_counties():
    # a county missing from Fall-2025 that is NOT a recognized gap (e.g. not
    # Connecticut) must NOT be silently backfilled from MCC
    mcc = load_mcc_customers(io.StringIO("County_FIPS,Customers\n54321,999\n"))
    table = build_customer_denominator_table(FALL2025_SAMPLE, mcc)
    assert "54321" not in set(table.county_fips)


def test_compute_county_outage_target_raises_for_unsupported_missing_county():
    outages = load_eaglei_outages(io.StringIO(EAGLEI_SAMPLE))
    mcc = load_mcc_customers(io.StringIO("County_FIPS,Customers\n54321,999\n"))
    table = build_customer_denominator_table(FALL2025_SAMPLE, mcc)
    with pytest.raises(ValueError, match="No customer denominator found"):
        compute_county_outage_target(outages, table, "54321", datetime(2018, 10, 10), datetime(2018, 10, 11))
