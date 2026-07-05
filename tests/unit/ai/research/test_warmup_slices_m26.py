"""M26 — the loop's OOS / hold-out / decay slices get a warm-up prefix (via C1's warmup_bars).

Review finding M26: those short re-evaluation slices fetched exactly the evaluation window and ran
from scratch, so a slow indicator burned most of the window unconverged and "decay" conflated a
warm-up artifact with real edge decay. The fix reaches back for a warm-up prefix and threads
warmup_bars through executor.run.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.backend.ai.research.executor import ResearchExecutor
from src.backend.ai.research.loop import _prepare_with_warmup, _spec_lookback
from tests.support.frozen_data import make_ohlcv


def test_spec_lookback_is_the_largest_period():
    assert _spec_lookback({"params": {"fast_period": 5, "slow_period": 40}}) == 40
    assert _spec_lookback({"params": {}}) == 0
    assert _spec_lookback({}) == 0


class _RecordingAgent:
    """A data agent that records the fetch windows and serves the requested slice of a fixed frame."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.calls: list[tuple[str, str]] = []

    def prepare(self, security_id: str, window_start: str, window_end: str):
        self.calls.append((str(window_start), str(window_end)))
        return self.df.loc[str(window_start):str(window_end)]


@pytest.mark.finding("M26")
def test_prepare_with_warmup_reaches_back_before_the_window():
    idx = pd.bdate_range("2020-01-01", "2021-01-01")
    df = pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=idx
    )
    agent = _RecordingAgent(df)
    spec = {"params": {"slow_period": 40}, "security_id": "T"}

    data, warmup = _prepare_with_warmup(agent, "T", "2020-06-01", "2020-09-01", spec)

    # It fetched a prefix BEFORE the window start …
    assert agent.calls[0][0] < "2020-06-01"
    # … and reported a positive warm-up count (bars preceding the window), leaving a scoring window.
    assert warmup > 0
    assert (data.index < pd.Timestamp("2020-06-01")).sum() == warmup
    assert warmup < len(data) - 2


@pytest.mark.finding("M26")
def test_no_lookback_spec_fetches_plain_window():
    agent = _RecordingAgent(
        pd.DataFrame({"Close": [1.0]}, index=pd.bdate_range("2020-01-01", periods=1))
    )
    _, warmup = _prepare_with_warmup(agent, "T", "2020-01-01", "2020-02-01", {"params": {}})
    assert warmup == 0
    assert agent.calls[0][0] == "2020-01-01"  # no reach-back when there's no lookback


@pytest.mark.finding("M26")
def test_executor_forwards_warmup_bars_and_windows_metrics():
    data = make_ohlcv(days=200, seed=4)
    ex = ResearchExecutor()
    spec = {"template_id": "sma_crossover", "params": {"fast_period": 5, "slow_period": 20}, "security_id": "T"}

    cold = ex.run(spec, data)
    warm = ex.run(spec, data, warmup_bars=60)

    # The warm run's reported equity curve is windowed past the 60-bar prefix.
    assert len(warm["equity_curve"]) < len(cold["equity_curve"])
    assert abs(len(warm["equity_curve"]) - (len(data) - 60)) <= 3
