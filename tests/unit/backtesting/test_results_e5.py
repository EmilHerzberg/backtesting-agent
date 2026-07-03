"""Tests for E-5 (ATS-207) finishing tickets: 215, 219, 224."""

from __future__ import annotations

import csv
import io
import json

import numpy as np
import pandas as pd
import pytest

from src.backend.backtesting.results.regime import (
    VolatilityBucket,
    classify_by_volatility,
    compute_atr,
)


# ---------------------------------------------------------------------- #
# ATS-215 — export_top_n JSON / CSV
# ---------------------------------------------------------------------- #


def _fake_query_with_rows(rows: list[dict]):
    """Build a thin double for ResultQuery exposing only export_top_n's path."""
    from src.backend.backtesting.results.query import ResultQuery

    class _Stub(ResultQuery):
        def __init__(self):
            pass  # bypass real init

        def top_n(self, *, n=10, metric="sharpe_ratio", criteria=None):
            return [_FakeTrial(**r) for r in rows[:n]]

    return _Stub()


class _FakeStrategy:
    def __init__(self, name):
        self.name = name


class _FakeTrial:
    def __init__(self, **fields):
        self.id = fields.get("id", 1)
        self.symbol = fields.get("symbol", "AAPL")
        self.interval = fields.get("interval", "1d")
        self.parameters = fields.get("parameters", {"period": 20})
        self.total_return = fields.get("total_return", 0.15)
        self.sharpe_ratio = fields.get("sharpe_ratio", 1.2)
        self.max_drawdown = fields.get("max_drawdown", 0.05)
        self.sortino_ratio = fields.get("sortino_ratio", 1.5)
        self.win_rate = fields.get("win_rate", 0.55)
        self.trade_count = fields.get("trade_count", 30)
        self.profit_factor = fields.get("profit_factor", 1.8)
        self.calmar_ratio = fields.get("calmar_ratio", 0.6)
        self.buy_hold_return = fields.get("buy_hold_return", 0.10)
        self.exposure_time = fields.get("exposure_time", 0.7)
        self.is_train = fields.get("is_train", False)
        self.overfitting_score = fields.get("overfitting_score", None)
        self.is_validated = fields.get("is_validated", True)
        self.created_at = fields.get("created_at", None)
        self.strategy = _FakeStrategy(fields.get("strategy_name", "SMACrossover"))


class TestExportTopN:
    def test_format_dict_returns_list_of_dicts(self):
        q = _fake_query_with_rows([{"id": 1, "symbol": "AAPL"}, {"id": 2, "symbol": "MSFT"}])
        rows = q.export_top_n(n=2, format="dict")
        assert isinstance(rows, list)
        assert len(rows) == 2
        assert rows[0]["trial_id"] == 1
        assert rows[1]["symbol"] == "MSFT"

    def test_format_json_serializes(self):
        q = _fake_query_with_rows([{"id": 1, "symbol": "AAPL"}])
        out = q.export_top_n(n=1, format="json")
        assert isinstance(out, str)
        parsed = json.loads(out)
        assert parsed[0]["trial_id"] == 1
        assert parsed[0]["symbol"] == "AAPL"
        # Nested params should be a real dict, not a string
        assert parsed[0]["parameters"] == {"period": 20}

    def test_format_csv_has_header_and_rows(self):
        q = _fake_query_with_rows([
            {"id": 1, "symbol": "AAPL"},
            {"id": 2, "symbol": "MSFT", "sharpe_ratio": 0.9},
        ])
        out = q.export_top_n(n=2, format="csv")
        assert isinstance(out, str)
        reader = list(csv.DictReader(io.StringIO(out)))
        assert len(reader) == 2
        assert reader[0]["symbol"] == "AAPL"
        assert reader[1]["symbol"] == "MSFT"
        # Nested parameters dict is JSON-encoded in the CSV cell
        assert json.loads(reader[0]["parameters"]) == {"period": 20}

    def test_format_csv_handles_empty_result(self):
        q = _fake_query_with_rows([])
        out = q.export_top_n(n=10, format="csv")
        # Header-only CSV still parses
        assert "trial_id" in out.splitlines()[0]
        assert len(list(csv.DictReader(io.StringIO(out)))) == 0

    def test_unknown_format_raises(self):
        q = _fake_query_with_rows([{"id": 1}])
        with pytest.raises(ValueError):
            q.export_top_n(format="xml")  # type: ignore[arg-type]

    def test_format_is_case_insensitive(self):
        q = _fake_query_with_rows([{"id": 1}])
        out = q.export_top_n(n=1, format="JSON")
        assert isinstance(out, str)
        assert json.loads(out)[0]["trial_id"] == 1


# ---------------------------------------------------------------------- #
# ATS-219 — Optuna parameter sensitivity
# ---------------------------------------------------------------------- #


class TestParameterSensitivity:
    def test_returns_dict_for_real_study(self):
        import optuna

        from src.backend.backtesting.results.visualize import (
            plot_parameter_sensitivity,
        )

        # Tiny synthetic study with two params and >= 10 trials so Optuna
        # has enough data for importance / contour / slice
        study = optuna.create_study(direction="maximize")

        def obj(trial):
            x = trial.suggest_float("x", -5.0, 5.0)
            y = trial.suggest_float("y", -5.0, 5.0)
            return -(x - 1) ** 2 - (y - 2) ** 2

        study.optimize(obj, n_trials=15, show_progress_bar=False)
        plots = plot_parameter_sensitivity(study)
        # At minimum the optimization-history view should exist (no preconditions)
        assert "history" in plots
        # Each value is a Plotly Figure
        for fig in plots.values():
            assert hasattr(fig, "to_html")

    def test_skips_failing_plots_silently(self):
        import optuna

        from src.backend.backtesting.results.visualize import (
            plot_parameter_sensitivity,
        )

        # Single-parameter study — plot_contour requires >=2, expect skip
        study = optuna.create_study(direction="maximize")

        def obj(trial):
            return trial.suggest_float("only", 0.0, 1.0)

        study.optimize(obj, n_trials=5, show_progress_bar=False)
        plots = plot_parameter_sensitivity(study)
        # Should not raise; history is always available
        assert "history" in plots


# ---------------------------------------------------------------------- #
# ATS-224 — VolatilityBucket / classify_by_volatility
# ---------------------------------------------------------------------- #


def _ohlc_with_step_volatility() -> pd.DataFrame:
    """Build OHLCV with a known low -> medium -> high -> extreme transition.

    Four 50-bar regimes give the quantile classifier enough spread to
    populate all four buckets.
    """
    dates = pd.date_range("2024-01-01", periods=200, freq="D")
    close = np.linspace(100, 110, 200)
    # 50 low (range=1), 50 medium (range=4), 50 high (range=8), 50 extreme (range=16)
    range_per_regime = np.concatenate([
        np.full(50, 0.5),
        np.full(50, 2.0),
        np.full(50, 4.0),
        np.full(50, 8.0),
    ])
    high = close + range_per_regime
    low = close - range_per_regime
    return pd.DataFrame(
        {
            "Open": close,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )


class TestVolatilityClassification:
    def test_atr_based_classifier_produces_multiple_buckets(self):
        df = _ohlc_with_step_volatility()
        buckets = classify_by_volatility(df)
        seen = set(buckets)
        # 4 distinct vol regimes -> at least 3 distinct buckets must appear
        assert len(seen) >= 3
        assert VolatilityBucket.LOW in seen
        assert VolatilityBucket.EXTREME in seen

    def test_uses_vix_when_provided(self):
        df = _ohlc_with_step_volatility()
        # VIX rising from 12 to 35 — classic calm -> stress transition
        vix = pd.Series(
            np.linspace(12.0, 35.0, len(df)), index=df.index, name="vix"
        )
        buckets = classify_by_volatility(df, vix_data=vix)
        # First bar (lowest VIX) -> LOW, last bar (highest VIX) -> EXTREME
        assert buckets.iloc[0] == VolatilityBucket.LOW
        assert buckets.iloc[-1] == VolatilityBucket.EXTREME

    def test_returns_series_aligned_to_input_index(self):
        df = _ohlc_with_step_volatility()
        buckets = classify_by_volatility(df)
        assert len(buckets) == len(df)
        assert buckets.index.equals(df.index)
        assert buckets.name == "volatility_bucket"

    def test_invalid_quantiles_raise(self):
        df = _ohlc_with_step_volatility()
        with pytest.raises(ValueError):
            classify_by_volatility(df, quantiles=(0.5, 0.4, 0.9))  # not increasing
        with pytest.raises(ValueError):
            classify_by_volatility(df, quantiles=(0.0, 0.5, 0.9))  # boundary

    def test_compute_atr_increases_with_range(self):
        df_low = _ohlc_with_step_volatility().iloc[:100]
        df_high = _ohlc_with_step_volatility().iloc[100:]
        # Same ATR window length but different range — high section should
        # produce a strictly larger mean ATR
        atr_low = compute_atr(df_low, period=14).iloc[-1]
        atr_high = compute_atr(df_high, period=14).iloc[-1]
        assert atr_high > atr_low

    def test_vix_with_missing_values_is_forward_filled(self):
        df = _ohlc_with_step_volatility()
        vix = pd.Series(np.nan, index=df.index)
        # Set only every 10th bar; rest must be ffilled, not crash
        vix.iloc[::10] = np.linspace(15.0, 30.0, len(vix.iloc[::10]))
        buckets = classify_by_volatility(df, vix_data=vix)
        # Every output is a valid bucket (no NaN)
        assert all(isinstance(b, VolatilityBucket) for b in buckets)
