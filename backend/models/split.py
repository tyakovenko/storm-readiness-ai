"""Period and storm-based dataset splitting for model validation without data leakage.

Ensures no temporal or spatial autocorrelation leakage between train and test sets:
1. Temporal Period Split (e.g. Train: 2014-2021, Test: 2022-2024)
2. Held-Out Storm Split (e.g. Idalia 2023, Hilary 2023, Michael 2018, Ian 2022)
3. Leave-One-Storm-Out Cross-Validation (LOSO-CV)
"""

from __future__ import annotations
import logging
from typing import Generator
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_HELD_OUT_STORMS = ["Idalia", "Hilary", "Michael", "Ian"]


def temporal_period_split(
    df: pd.DataFrame,
    train_end_year: int = 2021,
    test_start_year: int = 2022,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split dataset strictly by time period (years) to prevent temporal leakage.

    Args:
        df: DataFrame containing at least a 'year' column.
        train_end_year: Last year included in training set (default: 2021).
        test_start_year: First year included in testing set (default: 2022).

    Returns:
        (df_train, df_test) with guaranteed zero year overlap.
    """
    if "year" not in df.columns:
        raise ValueError("DataFrame must contain 'year' column for temporal splitting.")

    df_train = df[df["year"] <= train_end_year].copy()
    df_test = df[df["year"] >= test_start_year].copy()

    train_years = set(df_train["year"].unique())
    test_years = set(df_test["year"].unique())

    overlap = train_years.intersection(test_years)
    if overlap:
        raise ValueError(f"Temporal leakage detected! Overlapping years: {overlap}")

    log.info(
        f"Temporal Split: Train period {min(train_years, default='N/A')}-{max(train_years, default='N/A')} "
        f"({len(df_train)} samples) | Test period {min(test_years, default='N/A')}-{max(test_years, default='N/A')} "
        f"({len(df_test)} samples)"
    )
    return df_train, df_test


def held_out_storm_split(
    df: pd.DataFrame,
    held_out_storms: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split dataset by holding out entire storm events to evaluate generalization.

    Args:
        df: DataFrame containing at least a 'storm_name' column.
        held_out_storms: List of storm names to hold out for testing.
                         Defaults to proposal benchmark storms: Idalia, Hilary, Michael, Ian.

    Returns:
        (df_train, df_test) with guaranteed zero storm overlap.
    """
    if "storm_name" not in df.columns:
        raise ValueError("DataFrame must contain 'storm_name' column for storm-based splitting.")

    target_held_out = set(held_out_storms or DEFAULT_HELD_OUT_STORMS)
    df_train = df[~df["storm_name"].isin(target_held_out)].copy()
    df_test = df[df["storm_name"].isin(target_held_out)].copy()

    train_storms = set(df_train["storm_name"].unique())
    test_storms = set(df_test["storm_name"].unique())

    overlap = train_storms.intersection(test_storms)
    if overlap:
        raise ValueError(f"Storm leakage detected! Overlapping storms: {overlap}")

    log.info(
        f"Held-Out Storm Split: {len(train_storms)} training storms ({len(df_train)} samples) | "
        f"{len(test_storms)} test storms ({list(test_storms)}) ({len(df_test)} samples)"
    )
    return df_train, df_test


def leave_one_storm_out(
    df: pd.DataFrame,
) -> Generator[tuple[pd.DataFrame, pd.DataFrame, str], None, None]:
    """Generator yielding train/test splits leaving one storm out at a time."""
    if "storm_name" not in df.columns:
        raise ValueError("DataFrame must contain 'storm_name' column for Leave-One-Storm-Out CV.")

    unique_storms = sorted(df["storm_name"].unique())
    for storm in unique_storms:
        train_df = df[df["storm_name"] != storm]
        test_df = df[df["storm_name"] == storm]
        yield train_df, test_df, storm
