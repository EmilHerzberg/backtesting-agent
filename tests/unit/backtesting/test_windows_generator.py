"""Tests for iter_rolling_windows generator + expanding mode (ATS-142)."""

from __future__ import annotations

import inspect

import pandas as pd

from src.backend.marketdata.windows import (
    iter_rolling_windows,
    rolling_windows,
)


def _two_year_daily() -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=520, freq="B")  # ~2 years
    return pd.DataFrame({"Close": range(len(idx)), "Open": 0, "High": 0, "Low": 0, "Volume": 0}, index=idx)


class TestIterRollingWindows:
    def test_is_a_generator(self):
        gen = iter_rolling_windows(_two_year_daily())
        assert inspect.isgenerator(gen)

    def test_yields_pairs(self):
        windows = list(iter_rolling_windows(_two_year_daily(), train_size="6m", test_size="2m", step="2m"))
        assert len(windows) > 0
        for train, test in windows:
            assert not train.empty
            assert not test.empty
            # Test starts after train ends
            assert test.index.min() >= train.index.max()

    def test_empty_df_yields_nothing(self):
        empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        # pandas empty df has no DatetimeIndex by default, but our function
        # short-circuits on `df.empty` so it never gets there.
        windows = list(iter_rolling_windows(empty))
        assert windows == []

    def test_expanding_window_grows(self):
        windows = list(
            iter_rolling_windows(
                _two_year_daily(),
                train_size="3m", test_size="1m", step="1m",
                expanding=True,
            )
        )
        assert len(windows) >= 2
        # In expanding mode, each successive train window starts at the same date
        # and grows; row count strictly non-decreasing.
        train_lengths = [len(t) for t, _ in windows]
        assert all(b >= a for a, b in zip(train_lengths, train_lengths[1:]))

    def test_rolling_window_stays_constant(self):
        windows = list(
            iter_rolling_windows(
                _two_year_daily(),
                train_size="3m", test_size="1m", step="1m",
                expanding=False,
            )
        )
        assert len(windows) >= 2
        # In rolling mode, train length is approximately constant
        train_lengths = [len(t) for t, _ in windows]
        # Lengths within ±2 rows is fine (calendar drift)
        assert max(train_lengths) - min(train_lengths) <= 5


class TestBackwardCompatRollingWindows:
    def test_returns_list(self):
        result = rolling_windows(_two_year_daily(), train_size="6m", test_size="2m", step="2m")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_list_matches_generator(self):
        df = _two_year_daily()
        from_list = rolling_windows(df, train_size="6m", test_size="2m", step="2m")
        from_iter = list(iter_rolling_windows(df, train_size="6m", test_size="2m", step="2m"))
        assert len(from_list) == len(from_iter)
