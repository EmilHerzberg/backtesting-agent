"""Tests for SearchSpaceConfig + early-stop callback (ATS-181 / E3-S3-T3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.backtesting.engine.optimizer import (
    OptimizationConfig,
    _create_pruner,
    _make_early_stop_callback,
)
from src.backend.backtesting.strategies.generator import SearchSpaceConfig


class TestSearchSpaceConfig:
    def test_defaults(self):
        c = SearchSpaceConfig()
        assert c.min_indicators == 1
        assert c.max_indicators == 5
        assert c.conflicting_groups == []

    def test_min_must_be_positive(self):
        with pytest.raises(ValueError):
            SearchSpaceConfig(min_indicators=0)

    def test_max_must_exceed_min(self):
        with pytest.raises(ValueError):
            SearchSpaceConfig(min_indicators=3, max_indicators=2)

    def test_no_conflicts_allows_all(self):
        c = SearchSpaceConfig()
        assert c.is_compatible(["SMA", "RSI"], "EMA") is True
        assert c.is_compatible([], "ANYTHING") is True

    def test_conflict_blocks_second_member(self):
        c = SearchSpaceConfig(conflicting_groups=[["SMA", "EMA"]])
        # First indicator goes in
        assert c.is_compatible([], "SMA") is True
        # Second indicator from same group is blocked
        assert c.is_compatible(["SMA"], "EMA") is False
        # But unrelated indicators are fine
        assert c.is_compatible(["SMA"], "RSI") is True

    def test_conflict_is_case_insensitive(self):
        c = SearchSpaceConfig(conflicting_groups=[["sma", "ema"]])
        assert c.is_compatible(["SMA"], "ema") is False
        assert c.is_compatible(["sma"], "EMA") is False

    def test_multiple_groups_independent(self):
        c = SearchSpaceConfig(
            conflicting_groups=[["SMA", "EMA"], ["RSI", "STOCH"]],
        )
        assert c.is_compatible(["SMA"], "RSI") is True  # different group
        assert c.is_compatible(["SMA", "RSI"], "EMA") is False  # SMA group


class TestOptimizationConfigDefaults:
    def test_new_search_space_knobs_have_sensible_defaults(self):
        cfg = OptimizationConfig(strategy_class=object, data=None)  # type: ignore[arg-type]
        assert cfg.timeout_seconds is None
        assert cfg.pruner_warmup_trials == 10
        assert cfg.n_jobs == 1
        assert cfg.early_stop_patience is None


class TestPrunerWarmup:
    def test_median_pruner_uses_warmup(self):
        p = _create_pruner("median", warmup_trials=25)
        # MedianPruner exposes _n_startup_trials in Optuna >= 3.x
        assert getattr(p, "_n_startup_trials", None) == 25

    def test_unknown_pruner_falls_back_to_median_with_warmup(self):
        p = _create_pruner("garbage", warmup_trials=7)
        assert getattr(p, "_n_startup_trials", None) == 7


class TestEarlyStopCallback:
    def _frozen_trial(self, value):
        t = MagicMock()
        t.value = value
        return t

    def test_does_not_stop_below_patience(self):
        cb = _make_early_stop_callback(patience=3)
        study = MagicMock()
        study.best_value = 1.0
        # First trial — establishes baseline, no stop
        cb(study, self._frozen_trial(1.0))
        # Two stale trials — still under patience=3
        study.best_value = 1.0
        cb(study, self._frozen_trial(0.5))
        cb(study, self._frozen_trial(0.5))
        study.stop.assert_not_called()

    def test_stops_after_patience_consecutive_no_improvement(self):
        cb = _make_early_stop_callback(patience=2)
        study = MagicMock()
        study.best_value = 1.0
        # Baseline
        cb(study, self._frozen_trial(1.0))
        # Two stale trials — should hit patience=2 and call stop
        cb(study, self._frozen_trial(0.5))
        cb(study, self._frozen_trial(0.4))
        study.stop.assert_called_once()

    def test_skips_pruned_trials_with_none_value(self):
        cb = _make_early_stop_callback(patience=2)
        study = MagicMock()
        study.best_value = 1.0
        cb(study, self._frozen_trial(1.0))
        # Pruned trial — value is None, must NOT count as stale
        cb(study, self._frozen_trial(None))
        cb(study, self._frozen_trial(0.5))
        study.stop.assert_not_called()
        # Now hit patience
        cb(study, self._frozen_trial(0.4))
        study.stop.assert_called_once()
