"""Data quality checks and auto-fix utilities for backtesting DataFrames."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from src.backend.shared.types import BarInterval

logger = logging.getLogger(__name__)


@dataclass
class DataQualityReport:
    """Summary of all data quality checks on an OHLCV DataFrame."""

    symbol: str = ""
    row_count: int = 0
    date_range: tuple[datetime | None, datetime | None] = (None, None)
    gaps: list[str] = field(default_factory=list)
    plausibility_issues: list[str] = field(default_factory=list)
    adjustment_warnings: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.gaps and not self.plausibility_issues and not self.adjustment_warnings

    @property
    def total_issues(self) -> int:
        return len(self.gaps) + len(self.plausibility_issues) + len(self.adjustment_warnings)

    def summary(self) -> str:
        lines = [f"Data Quality Report for {self.symbol}"]
        lines.append(f"  Rows: {self.row_count}")
        if self.date_range[0] and self.date_range[1]:
            lines.append(f"  Range: {self.date_range[0]} -> {self.date_range[1]}")
        lines.append(f"  Gaps: {len(self.gaps)}")
        lines.append(f"  Plausibility issues: {len(self.plausibility_issues)}")
        lines.append(f"  Adjustment warnings: {len(self.adjustment_warnings)}")
        lines.append(f"  Clean: {self.is_clean}")
        return "\n".join(lines)


# Approximate expected gap between bars
_INTERVAL_DELTA: dict[BarInterval, timedelta] = {
    BarInterval.ONE_MIN: timedelta(minutes=1),
    BarInterval.FIVE_MIN: timedelta(minutes=5),
    BarInterval.FIFTEEN_MIN: timedelta(minutes=15),
    BarInterval.ONE_HOUR: timedelta(hours=1),
    BarInterval.ONE_DAY: timedelta(days=1),
}


class DataQualityChecker:
    """Runs quality checks on OHLCV DataFrames."""

    def check_gaps(
        self,
        df: pd.DataFrame,
        interval: BarInterval = BarInterval.ONE_DAY,
    ) -> list[str]:
        """Detect gaps (missing dates/times) in the DataFrame index.

        For daily data, weekends and common US holidays are excluded.
        Returns a list of human-readable gap descriptions.
        """
        if df.empty or len(df) < 2:
            return []

        gaps: list[str] = []
        expected_delta = _INTERVAL_DELTA.get(interval, timedelta(days=1))

        if interval == BarInterval.ONE_DAY:
            # For daily data, use business day logic
            bdays = pd.bdate_range(start=df.index.min(), end=df.index.max())
            actual_dates = set(df.index.normalize())
            missing = sorted(set(bdays) - actual_dates)
            for dt in missing:
                gaps.append(f"Missing trading day: {dt.strftime('%Y-%m-%d')}")
        else:
            # For intraday, check consecutive bar gaps
            index_sorted = df.index.sort_values()
            diffs = index_sorted.to_series().diff()
            max_gap = expected_delta * 3  # allow some tolerance
            for i in range(1, len(diffs)):
                if pd.notna(diffs.iloc[i]) and diffs.iloc[i] > max_gap:
                    gap_start = index_sorted[i - 1]
                    gap_end = index_sorted[i]
                    gaps.append(
                        f"Gap from {gap_start} to {gap_end} "
                        f"({diffs.iloc[i]} vs expected ~{expected_delta})"
                    )

        return gaps

    def check_plausibility(self, df: pd.DataFrame) -> list[str]:
        """Check for implausible data: negative prices, OHLC inconsistency, extreme moves.

        Returns a list of issue descriptions.
        """
        issues: list[str] = []
        if df.empty:
            return issues

        # Negative or zero prices
        for col in ["Open", "High", "Low", "Close"]:
            if col in df.columns:
                neg_count = (df[col] <= 0).sum()
                if neg_count > 0:
                    dates = df.index[df[col] <= 0].tolist()
                    issues.append(
                        f"{neg_count} rows with {col} <= 0: "
                        f"{[str(d)[:10] for d in dates[:5]]}"
                    )

        # OHLC consistency: High >= Low, High >= Open, High >= Close, Low <= Open, Low <= Close
        if {"High", "Low", "Open", "Close"}.issubset(df.columns):
            bad_hl = df[df["High"] < df["Low"]]
            if not bad_hl.empty:
                issues.append(
                    f"{len(bad_hl)} rows where High < Low: "
                    f"{[str(d)[:10] for d in bad_hl.index[:5]]}"
                )

            bad_ho = df[df["High"] < df["Open"]]
            if not bad_ho.empty:
                issues.append(
                    f"{len(bad_ho)} rows where High < Open: "
                    f"{[str(d)[:10] for d in bad_ho.index[:5]]}"
                )

            bad_hc = df[df["High"] < df["Close"]]
            if not bad_hc.empty:
                issues.append(
                    f"{len(bad_hc)} rows where High < Close: "
                    f"{[str(d)[:10] for d in bad_hc.index[:5]]}"
                )

            bad_lo = df[df["Low"] > df["Open"]]
            if not bad_lo.empty:
                issues.append(
                    f"{len(bad_lo)} rows where Low > Open: "
                    f"{[str(d)[:10] for d in bad_lo.index[:5]]}"
                )

            bad_lc = df[df["Low"] > df["Close"]]
            if not bad_lc.empty:
                issues.append(
                    f"{len(bad_lc)} rows where Low > Close: "
                    f"{[str(d)[:10] for d in bad_lc.index[:5]]}"
                )

        # Extreme daily moves (>50%)
        if "Close" in df.columns and len(df) > 1:
            returns = df["Close"].pct_change().abs()
            extreme = returns[returns > 0.50]
            if not extreme.empty:
                for dt, ret in extreme.items():
                    issues.append(
                        f"Extreme move on {str(dt)[:10]}: {ret:.1%} daily change"
                    )

        # Negative volume
        if "Volume" in df.columns:
            neg_vol = (df["Volume"] < 0).sum()
            if neg_vol > 0:
                issues.append(f"{neg_vol} rows with negative Volume")

        return issues

    def check_adjustments(self, df: pd.DataFrame) -> list[str]:
        """Warn about potential unadjusted data (stock splits, large overnight gaps).

        Returns a list of warning strings.
        """
        warnings: list[str] = []
        if df.empty or "Close" not in df.columns or len(df) < 2:
            return warnings

        returns = df["Close"].pct_change()

        # Detect potential stock splits: exact ratio jumps (2:1, 3:1, etc.)
        for ratio in [0.5, 1.0 / 3.0, 0.25, 2.0, 3.0, 4.0]:
            # Check if close-to-close ratio is near a split ratio
            close_ratios = df["Close"] / df["Close"].shift(1)
            near_ratio = close_ratios[
                (close_ratios > ratio * 0.98) & (close_ratios < ratio * 1.02)
                & (close_ratios != 1.0)
            ]
            if not near_ratio.empty and ratio not in (1.0,):
                for dt in near_ratio.index[:3]:
                    actual = close_ratios.loc[dt]
                    warnings.append(
                        f"Potential split/reverse-split on {str(dt)[:10]}: "
                        f"close ratio {actual:.4f} (near {ratio})"
                    )

        return warnings

    def validate(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        interval: BarInterval = BarInterval.ONE_DAY,
    ) -> DataQualityReport:
        """Run all quality checks and return a consolidated report."""
        report = DataQualityReport(
            symbol=symbol,
            row_count=len(df),
        )

        if not df.empty:
            report.date_range = (
                df.index.min().to_pydatetime(),
                df.index.max().to_pydatetime(),
            )

        report.gaps = self.check_gaps(df, interval)
        report.plausibility_issues = self.check_plausibility(df)
        report.adjustment_warnings = self.check_adjustments(df)

        return report


# ------------------------------------------------------------------ #
# Auto-fix utilities
# ------------------------------------------------------------------ #

def fill_gaps(
    df: pd.DataFrame,
    method: str = "ffill",
    interval: BarInterval = BarInterval.ONE_DAY,
) -> pd.DataFrame:
    """Fill gaps in the DataFrame using the specified method.

    Args:
        df: OHLCV DataFrame with DatetimeIndex.
        method: Fill method — "ffill" (forward fill) or "bfill" (backward fill).
        interval: Bar interval, used to generate the expected index for daily data.

    Returns:
        DataFrame with gaps filled.
    """
    if df.empty:
        return df.copy()

    df = df.copy()

    if interval == BarInterval.ONE_DAY:
        full_index = pd.bdate_range(start=df.index.min(), end=df.index.max())
        df = df.reindex(full_index)
    # For intraday, just fillna without reindexing (generating all minute/hour
    # timestamps would require knowledge of trading hours).

    if method == "ffill":
        df = df.ffill()
    elif method == "bfill":
        df = df.bfill()
    else:
        df = df.ffill()

    # Drop any remaining NaN rows (e.g., leading NaNs from bfill)
    df = df.dropna(subset=["Close"])
    df.index.name = "Date"
    return df


def remove_outliers(
    df: pd.DataFrame,
    max_daily_change: float = 0.50,
) -> pd.DataFrame:
    """Remove rows with extreme price changes.

    Args:
        df: OHLCV DataFrame.
        max_daily_change: Maximum allowed absolute daily return (0.50 = 50%).

    Returns:
        DataFrame with outlier rows removed.
    """
    if df.empty or "Close" not in df.columns or len(df) < 2:
        return df.copy()

    df = df.copy()
    returns = df["Close"].pct_change().abs()
    # Keep first row (NaN return) and rows within threshold
    mask = (returns <= max_daily_change) | returns.isna()
    removed = (~mask).sum()
    if removed > 0:
        logger.info("Removed %d outlier rows (>%.0f%% daily change)", removed, max_daily_change * 100)
    return df[mask].copy()
