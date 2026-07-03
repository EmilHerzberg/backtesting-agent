"""Window selection and splitting utilities for backtesting."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass
class LookbackConfig:
    """Configure the lookback period for backtesting data.

    Provide either a human-readable period string (e.g., "2y", "6m", "90d")
    or explicit start/end dates. If both are given, start/end take precedence.
    """

    period: str | None = None
    start: datetime | None = None
    end: datetime | None = None

    def resolve(self, reference_date: datetime | None = None) -> tuple[datetime, datetime]:
        """Resolve to concrete (start, end) datetimes.

        Args:
            reference_date: The "now" reference. Defaults to today.

        Returns:
            Tuple of (start, end) datetimes.
        """
        ref = reference_date or datetime.now()

        if self.start is not None and self.end is not None:
            return (self.start, self.end)

        end = self.end or ref

        if self.start is not None:
            return (self.start, end)

        if self.period is not None:
            delta = _parse_period(self.period)
            start = end - delta
            return (start, end)

        # Default: 2 years
        return (end - pd.DateOffset(years=2), end)


def _parse_period(period: str) -> pd.DateOffset:
    """Parse a period string like '2y', '6m', '90d', '52w' into a DateOffset."""
    match = re.match(r"^(\d+)\s*([yYmMwWdD])$", period.strip())
    if not match:
        raise ValueError(
            f"Invalid period format '{period}'. "
            "Use e.g. '2y' (years), '6m' (months), '4w' (weeks), '90d' (days)."
        )

    amount = int(match.group(1))
    unit = match.group(2).lower()

    if unit == "y":
        return pd.DateOffset(years=amount)
    elif unit == "m":
        return pd.DateOffset(months=amount)
    elif unit == "w":
        return pd.DateOffset(weeks=amount)
    elif unit == "d":
        return pd.DateOffset(days=amount)
    else:
        raise ValueError(f"Unknown period unit '{unit}'")


def train_test_split(
    df: pd.DataFrame,
    test_ratio: float = 0.25,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a time-series DataFrame chronologically (no shuffle).

    Args:
        df: OHLCV DataFrame with DatetimeIndex, assumed sorted.
        test_ratio: Fraction of data to use for testing (from the end).

    Returns:
        Tuple of (train_df, test_df).
    """
    if df.empty:
        return df.copy(), df.copy()

    df = df.sort_index()
    n = len(df)
    split_idx = int(n * (1 - test_ratio))
    split_idx = max(1, min(split_idx, n - 1))  # ensure both sets are non-empty

    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()
    return train_df, test_df


def iter_rolling_windows(
    df: pd.DataFrame,
    train_size: str = "12m",
    test_size: str = "3m",
    step: str = "3m",
    *,
    expanding: bool = False,
):
    """Yield rolling (or expanding) walk-forward train/test window pairs.

    Generator variant of :func:`rolling_windows` (ATS-142). Memory-friendly
    for very long histories — consumers can stream window pairs without
    materialising the full list.

    Args:
        df: OHLCV DataFrame with DatetimeIndex, assumed sorted.
        train_size: Training window length (e.g., "12m", "1y", "252d").
        test_size: Test window length.
        step: Step size between consecutive windows.
        expanding: If True, the training window grows from ``data_start``
            up to ``train_end`` instead of staying at fixed length. Default
            False (rolling, fixed-width window).

    Yields:
        ``(train_df, test_df)`` tuples.
    """
    if df.empty:
        return

    df = df.sort_index()
    train_offset = _parse_period(train_size)
    test_offset = _parse_period(test_size)
    step_offset = _parse_period(step)

    data_start = df.index.min()
    data_end = df.index.max()
    window_start = data_start

    while True:
        train_end = window_start + train_offset
        test_end = train_end + test_offset

        # Stop if we've run past available data
        if train_end > data_end:
            break

        # Expanding window: train always starts at data_start; rolling: at window_start.
        train_lo = data_start if expanding else window_start
        train_df = df[(df.index >= train_lo) & (df.index < train_end)].copy()
        test_df = df[(df.index >= train_end) & (df.index < test_end)].copy()

        if not train_df.empty and not test_df.empty:
            yield train_df, test_df

        window_start = window_start + step_offset


def rolling_windows(
    df: pd.DataFrame,
    train_size: str = "12m",
    test_size: str = "3m",
    step: str = "3m",
    *,
    expanding: bool = False,
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Materialised list of rolling walk-forward window pairs.

    Backward-compatible wrapper around :func:`iter_rolling_windows`.
    """
    return list(
        iter_rolling_windows(
            df,
            train_size=train_size,
            test_size=test_size,
            step=step,
            expanding=expanding,
        )
    )
