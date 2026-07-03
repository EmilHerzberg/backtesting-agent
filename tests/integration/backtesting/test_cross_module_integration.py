"""Cross-module integration tests for Sprint 1-5 backtesting subsystem.

These tests verify that the backtesting modules actually work together
correctly -- not just in isolation.  Each test exercises a realistic
flow that spans two or more modules and checks the contract at each
seam.

Modules under test:
  - registry.definition (StrategyDefinition + content-hash)
  - registry.runspec    (RunSpec + evaluation context)
  - registry.event_registry (TrialEventRegistry, lifecycle events)
  - registry.snapshot   (DataSnapshot + OHLCV content-hash)
  - gates.pipeline      (GatePipeline, GateContext, short-circuit)
  - gates.basic_gates   (SpecValidation, MinimumActivity, PerformanceFloor,
                          BenchmarkRelativeGate)
  - gates.deflated_sharpe (DSR computation + gate)
  - benchmarks.buy_hold (compute_buy_hold)
  - lockbox.service     (OOSLockboxService, budget, terminal results)
"""

from __future__ import annotations

import json
import math
import re
import tempfile
import uuid
from datetime import date

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.backend.backtesting.benchmarks.buy_hold import (
    BenchmarkResult,
    compute_buy_hold,
)
from src.backend.backtesting.gates.basic_gates import (
    BenchmarkRelativeGate,
    MinimumActivityGate,
    PerformanceFloorGate,
    SpecValidationGate,
)
from src.backend.backtesting.gates.deflated_sharpe import (
    DeflatedSharpeGate,
    deflated_sharpe,
)
from src.backend.backtesting.gates.pipeline import (
    Gate,
    GateContext,
    GatePipeline,
    GateResult,
    GateSeverity,
    GateStatus,
)
from src.backend.backtesting.lockbox.service import (
    AlreadyEvaluatedError,
    BudgetExhaustedError,
    OOSLockboxService,
    OOSOutcome,
    PromotionToken,
)
from src.backend.backtesting.registry.definition import (
    StrategyDefinition,
    canonical_json,
)
from src.backend.backtesting.registry.event_registry import (
    EventType,
    TrialEventRegistry,
)
from src.backend.backtesting.registry.models import RegistryBase
from src.backend.backtesting.registry.runspec import EvaluationRole, RunSpec
from src.backend.backtesting.registry.snapshot import (
    DataSnapshot,
    compute_data_snapshot_hash,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_strategy_definition(**overrides) -> StrategyDefinition:
    """Build a realistic StrategyDefinition with sensible defaults."""
    defaults = dict(
        template_id="sma_crossover",
        template_version=1,
        template_hash="t" * 64,
        params={"fast_period": 10, "slow_period": 30},
        security_id="AAPL",
        bar_size="1d",
        cost_profile_id="default",
        cost_profile_hash="c" * 64,
        execution_semantics={"fill_model": "next_open"},
        strategy_family="trend",
    )
    defaults.update(overrides)
    return StrategyDefinition(**defaults)


def _make_run_spec(strategy_hash: str, data_snapshot_hash: str = "d" * 64, **overrides) -> RunSpec:
    """Build a RunSpec tying a strategy to an evaluation window."""
    defaults = dict(
        strategy_hash=strategy_hash,
        evaluation_role=EvaluationRole.IS,
        window_start=date(2018, 1, 2),
        window_end=date(2023, 12, 29),
        data_snapshot_hash=data_snapshot_hash,
    )
    defaults.update(overrides)
    return RunSpec(**defaults)


def _make_gate_context(**overrides) -> GateContext:
    """Build a GateContext with realistic backtest-result-like data."""
    rng = np.random.default_rng(42)
    defaults = dict(
        metrics={
            "n_trades": 120,
            "sharpe_annual": 1.2,
            "total_return": 0.35,
            "max_drawdown": -0.12,
            "exposure_time": 0.55,
            "commission": 0.001,
        },
        trades=[],
        returns=rng.standard_normal(252) * 0.01 + 0.0003,
        equity_curve=[10000 + i * 15 for i in range(252)],
        strategy_hash="a" * 64,
        template_id="sma_crossover",
    )
    defaults.update(overrides)
    return GateContext(**defaults)


def _make_ohlcv(n: int = 500, seed: int = 42, drift: float = 0.0003) -> pd.DataFrame:
    """Create synthetic OHLCV data with controlled drift."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-02", periods=n, freq="B")
    returns = rng.normal(drift, 0.015, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
    open_ = np.roll(close, 1) * (1 + rng.normal(0, 0.002, n))
    open_[0] = close[0]
    return pd.DataFrame(
        {
            "Open": open_,
            "High": np.maximum(high, np.maximum(open_, close)),
            "Low": np.minimum(low, np.minimum(open_, close)),
            "Close": close,
            "Volume": rng.integers(100_000, 1_000_000, n),
        },
        index=idx,
    )


@pytest.fixture
def registry_session():
    """In-memory SQLite session with all registry tables."""
    engine = create_engine("sqlite:///:memory:")
    RegistryBase.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def registry(registry_session):
    return TrialEventRegistry(registry_session)


# ===========================================================================
# Test 1: StrategyDefinition -> RunSpec -> Registry flow
# ===========================================================================


class TestDefinitionRunSpecRegistryFlow:
    """Verify that a strategy definition flows through to the event-sourced
    registry with correct hashing, event lifecycle, and status derivation."""

    def test_full_lifecycle_queued_to_completed(self, registry, registry_session):
        # 1. Create a StrategyDefinition and compute its hash.
        defn = _make_strategy_definition()
        strategy_hash = defn.strategy_hash
        assert len(strategy_hash) == 64
        assert strategy_hash == defn.strategy_hash  # deterministic

        # 2. Create a RunSpec referencing that strategy_hash.
        run_spec = _make_run_spec(strategy_hash)
        assert run_spec.strategy_hash == strategy_hash
        assert len(run_spec.run_spec_hash) == 64

        # 3. Register both in the TrialEventRegistry.
        registry.register_strategy(
            definition_json=defn.model_dump_json(),
            strategy_hash=strategy_hash,
            template_id=defn.template_id,
            template_version=defn.template_version,
            template_hash=defn.template_hash,
            security_id=defn.security_id,
            cost_profile_id=defn.cost_profile_id,
            cost_profile_hash=defn.cost_profile_hash,
            strategy_family=defn.strategy_family,
        )

        registry.register_run_spec(
            run_spec_json=run_spec.model_dump_json(),
            run_spec_hash=run_spec.run_spec_hash,
            strategy_hash=strategy_hash,
            evaluation_role=run_spec.evaluation_role.value,
            window_start=str(run_spec.window_start),
            window_end=str(run_spec.window_end),
            data_snapshot_hash=run_spec.data_snapshot_hash,
        )

        run_id = registry.register_run(
            run_spec_hash=run_spec.run_spec_hash,
            strategy_hash=strategy_hash,
        )
        assert run_id.startswith("run_")

        # 4. Emit lifecycle events: QUEUED -> STARTED -> COMPLETED.
        registry.append_event(run_id, EventType.RUN_QUEUED)
        assert registry.get_current_status(run_id) == EventType.RUN_QUEUED

        registry.append_event(run_id, EventType.RUN_STARTED)
        assert registry.get_current_status(run_id) == EventType.RUN_STARTED

        registry.append_event(run_id, EventType.RUN_COMPLETED)
        registry_session.commit()

        # 5. Query status -- should be COMPLETED.
        status = registry.get_current_status(run_id)
        assert status == EventType.RUN_COMPLETED

        # 6. Query trial_count -- should be 1.
        assert registry.audit_trial_count() == 1

    def test_run_exists_idempotency(self, registry, registry_session):
        """After registering a run, run_exists returns True for that spec hash."""
        defn = _make_strategy_definition()
        run_spec = _make_run_spec(defn.strategy_hash)

        registry.register_strategy(
            definition_json=defn.model_dump_json(),
            strategy_hash=defn.strategy_hash,
            template_id=defn.template_id,
            template_version=defn.template_version,
            template_hash=defn.template_hash,
            security_id=defn.security_id,
            cost_profile_id=defn.cost_profile_id,
            cost_profile_hash=defn.cost_profile_hash,
            strategy_family=defn.strategy_family,
        )
        registry.register_run_spec(
            run_spec_json=run_spec.model_dump_json(),
            run_spec_hash=run_spec.run_spec_hash,
            strategy_hash=defn.strategy_hash,
            evaluation_role=run_spec.evaluation_role.value,
            window_start=str(run_spec.window_start),
            window_end=str(run_spec.window_end),
            data_snapshot_hash=run_spec.data_snapshot_hash,
        )
        registry.register_run(
            run_spec_hash=run_spec.run_spec_hash,
            strategy_hash=defn.strategy_hash,
        )
        registry_session.commit()

        assert registry.run_exists(run_spec.run_spec_hash) is True
        assert registry.run_exists("nonexistent" + "0" * 55) is False


# ===========================================================================
# Test 2: BacktestResult -> GateContext -> GatePipeline flow
# ===========================================================================


class TestBacktestResultGatePipelineFlow:
    """Verify that realistic backtest metrics flow through the gate
    pipeline with correct ordering and short-circuit behavior."""

    def test_pipeline_ordering_and_pass(self):
        """Gates are evaluated in cost_rank order; good metrics pass all."""
        ctx = _make_gate_context()
        pipeline = GatePipeline([
            PerformanceFloorGate(),   # cost_rank=5
            MinimumActivityGate(),    # cost_rank=4
            SpecValidationGate(),     # cost_rank=0
        ])

        report = pipeline.evaluate(ctx)

        # Verify cost_rank ascending order.
        ranks = [r.cost_rank for r in report.results]
        assert ranks == sorted(ranks), f"Expected sorted cost_ranks, got {ranks}"
        assert ranks == [0, 4, 5]

        # All should pass.
        assert report.passed is True
        assert all(r.status == GateStatus.PASS for r in report.results)

    def test_short_circuit_on_hard_failure(self):
        """When a hard gate fails, subsequent gates are NOT_EVALUATED."""
        ctx = _make_gate_context(
            metrics={
                "n_trades": 5,  # too few -- will fail MinimumActivityGate
                "sharpe_annual": 1.2,
                "total_return": 0.35,
                "exposure_time": 0.55,
            }
        )
        pipeline = GatePipeline([
            SpecValidationGate(),     # cost_rank=0 -> PASS
            MinimumActivityGate(),    # cost_rank=4 -> FAIL (hard)
            PerformanceFloorGate(),   # cost_rank=5 -> NOT_EVALUATED
        ])

        report = pipeline.evaluate(ctx)

        assert report.passed is False
        assert report.first_failed_gate == "minimum_activity"
        assert report.results[0].status == GateStatus.PASS
        assert report.results[1].status == GateStatus.FAIL
        assert report.results[2].status == GateStatus.NOT_EVALUATED

    def test_spec_validation_rejects_empty_hash(self):
        """SpecValidationGate fails when strategy_hash is empty."""
        ctx = _make_gate_context(strategy_hash="", template_id="sma")
        gate = SpecValidationGate()
        result = gate.check(ctx)
        assert result.status == GateStatus.FAIL

    def test_performance_floor_rejects_low_sharpe(self):
        """PerformanceFloorGate fails when Sharpe is below 0.5."""
        ctx = _make_gate_context(
            metrics={"sharpe_annual": 0.3, "total_return": 0.10}
        )
        gate = PerformanceFloorGate()
        result = gate.check(ctx)
        assert result.status == GateStatus.FAIL
        assert result.threshold == 0.5


# ===========================================================================
# Test 3: Buy-and-hold benchmark -> BenchmarkRelativeGate flow
# ===========================================================================


class TestBuyHoldBenchmarkGateFlow:
    """Verify that synthetic OHLCV data flows through the buy-hold
    benchmark computation and into the BenchmarkRelativeGate."""

    def test_strategy_beats_benchmark_passes(self):
        """When strategy metrics exceed the buy-hold benchmark, gate passes."""
        # Create uptrending data.
        df = _make_ohlcv(500, seed=42, drift=0.0003)
        bm = compute_buy_hold(df)

        assert isinstance(bm, BenchmarkResult)
        assert bm.total_return > 0  # mild uptrend
        assert len(bm.daily_returns) > 0

        # Strategy that clearly beats benchmark.
        ctx = _make_gate_context(
            metrics={
                "sharpe_annual": bm.annualized_sharpe + 0.5,  # beat by 0.5
                "total_return": bm.total_return + 0.10,
                "max_drawdown": bm.max_drawdown * 0.5,  # half the drawdown
            },
            benchmark={
                "buy_hold_sharpe": bm.annualized_sharpe,
                "buy_hold_return": bm.total_return,
                "buy_hold_max_drawdown": bm.max_drawdown,
            },
        )
        gate = BenchmarkRelativeGate()
        result = gate.check(ctx)
        assert result.passed, f"Expected PASS, got {result.status}: {result.details}"

    def test_strategy_loses_to_benchmark_fails(self):
        """When strategy is worse than buy-hold on every dimension, gate fails."""
        df = _make_ohlcv(500, seed=42, drift=0.0003)
        bm = compute_buy_hold(df)

        # Strategy that badly underperforms benchmark.
        ctx = _make_gate_context(
            metrics={
                "sharpe_annual": bm.annualized_sharpe - 1.0,  # much worse
                "total_return": bm.total_return - 0.20,        # lower return
                "max_drawdown": bm.max_drawdown * 2.0,         # worse drawdown
            },
            benchmark={
                "buy_hold_sharpe": bm.annualized_sharpe,
                "buy_hold_return": bm.total_return,
                "buy_hold_max_drawdown": bm.max_drawdown,
            },
        )
        gate = BenchmarkRelativeGate()
        result = gate.check(ctx)
        assert result.status == GateStatus.FAIL
        assert result.details.get("path_a_sharpe") is False
        assert result.details.get("path_c_excess_return") is False

    def test_no_benchmark_available_provisional_pass(self):
        """When no benchmark data is provided, gate passes provisionally."""
        ctx = _make_gate_context(benchmark={})
        gate = BenchmarkRelativeGate()
        result = gate.check(ctx)
        assert result.passed
        assert result.details.get("reason") == "no benchmark available, skipping"

    def test_benchmark_computation_on_flat_data(self):
        """Flat data produces near-zero return and Sharpe."""
        rng = np.random.default_rng(99)
        idx = pd.date_range("2020-01-01", periods=100, freq="B")
        close = 100.0 + rng.normal(0, 0.01, 100)  # ~flat
        df = pd.DataFrame({"Close": close}, index=idx)
        bm = compute_buy_hold(df)
        assert abs(bm.total_return) < 0.05  # near zero
        assert abs(bm.annualized_sharpe) < 2.0  # reasonable range


# ===========================================================================
# Test 4: DSR with real registry data
# ===========================================================================


class TestDSRWithRealRegistryData:
    """Verify that the Deflated Sharpe Ratio computation works end-to-end
    with Sharpe distributions extracted from the event-sourced registry."""

    def test_dsr_from_seeded_registry(self, registry, registry_session):
        """Seed 10 runs with known Sharpe ratios, compute DSR from the
        distribution, and verify the result is in [0, 1]."""
        known_sharpes = [0.01, 0.03, -0.01, 0.05, 0.02,
                         -0.005, 0.04, 0.015, 0.025, 0.035]

        for i, sr in enumerate(known_sharpes):
            strategy_hash = f"s{i:063d}"
            run_spec_hash = f"r{i:063d}"

            registry.register_strategy(
                definition_json="{}",
                strategy_hash=strategy_hash,
                template_id="sma",
                template_version=1,
                template_hash="t" * 64,
                security_id="AAPL",
                cost_profile_id="default",
                cost_profile_hash="c" * 64,
                strategy_family="trend",
            )
            registry.register_run_spec(
                run_spec_json="{}",
                run_spec_hash=run_spec_hash,
                strategy_hash=strategy_hash,
                evaluation_role="IS",
                window_start="2018-01-02",
                window_end="2023-12-29",
                data_snapshot_hash="d" * 64,
            )
            run_id = registry.register_run(
                run_id=f"run_{i:04d}",
                run_spec_hash=run_spec_hash,
                strategy_hash=strategy_hash,
            )
            registry.record_metrics(
                run_id=run_id,
                strategy_hash=strategy_hash,
                evaluation_role="IS",
                sharpe_perbar=sr,
                valid_research_trial=1,
            )
        registry_session.commit()

        # Query sharpe_distribution from the registry.
        dist = registry.sharpe_distribution()
        assert isinstance(dist, np.ndarray)
        assert len(dist) == 10
        np.testing.assert_allclose(sorted(dist), sorted(known_sharpes))

        # Compute DSR using the real distribution variance.
        sr_variance = float(np.var(dist, ddof=1))
        assert sr_variance > 0

        # Create a "good" strategy's returns.
        rng = np.random.default_rng(123)
        good_returns = rng.normal(0.001, 0.01, 252)  # positive drift

        dsr = deflated_sharpe(good_returns, n_trials=10, trial_sr_variance=sr_variance)
        assert 0.0 <= dsr <= 1.0, f"DSR {dsr} outside [0, 1]"

    def test_dsr_gate_with_registry_data(self, registry, registry_session):
        """DeflatedSharpeGate uses registry-seeded n_trials and sr_variance."""
        # Seed a few trials.
        sharpes = [0.02, 0.03, 0.01, -0.01, 0.04]
        for i, sr in enumerate(sharpes):
            sh = f"s{i:063d}"
            rsh = f"r{i:063d}"
            registry.register_strategy(
                definition_json="{}", strategy_hash=sh,
                template_id="test", template_version=1,
                template_hash="t" * 64, security_id="AAPL",
                cost_profile_id="default", cost_profile_hash="c" * 64,
                strategy_family="trend",
            )
            registry.register_run_spec(
                run_spec_json="{}", run_spec_hash=rsh,
                strategy_hash=sh, evaluation_role="IS",
                window_start="2018-01-02", window_end="2023-12-29",
                data_snapshot_hash="d" * 64,
            )
            rid = registry.register_run(
                run_id=f"run_{i}", run_spec_hash=rsh, strategy_hash=sh,
            )
            registry.record_metrics(
                run_id=rid, strategy_hash=sh,
                evaluation_role="IS", sharpe_perbar=sr,
            )
        registry_session.commit()

        dist = registry.sharpe_distribution()
        n_trials = registry.valid_research_trial_count()
        sr_var = float(np.var(dist, ddof=1))

        rng = np.random.default_rng(77)
        strategy_returns = rng.normal(0.0008, 0.012, 252)

        ctx = _make_gate_context(
            returns=strategy_returns,
            n_trials_global=n_trials,
            trial_sr_variance=sr_var,
        )

        gate = DeflatedSharpeGate()
        result = gate.check(ctx)
        # With only 5 trials, it should pass provisionally.
        assert result.passed
        assert result.details.get("provisional") is True


# ===========================================================================
# Test 5: Lockbox budget -> registry event flow
# ===========================================================================


class TestLockboxBudgetFlow:
    """Verify that the OOS lockbox service enforces budget limits,
    records terminal results, and blocks overwriting."""

    def test_budget_consumed_and_exhausted(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        svc = OOSLockboxService(db_path=db_path)
        lineage_id = "lin_test_budget"
        svc.ensure_budget(lineage_id, total=2)

        assert svc.remaining_budget(lineage_id) == 2

        # Evaluate 1: PASS
        token1 = PromotionToken("human_1", f"hash_{uuid.uuid4().hex[:8]}", lineage_id)
        outcome1 = svc.evaluate(token1, run_oos_backtest=lambda: True)
        assert outcome1 == OOSOutcome.PASS
        assert svc.remaining_budget(lineage_id) == 1

        # Evaluate 2: FAIL
        token2 = PromotionToken("human_1", f"hash_{uuid.uuid4().hex[:8]}", lineage_id)
        outcome2 = svc.evaluate(token2, run_oos_backtest=lambda: False)
        assert outcome2 == OOSOutcome.FAIL
        assert svc.remaining_budget(lineage_id) == 0

        # Evaluate 3: BudgetExhaustedError
        token3 = PromotionToken("human_1", f"hash_{uuid.uuid4().hex[:8]}", lineage_id)
        with pytest.raises(BudgetExhaustedError):
            svc.evaluate(token3, run_oos_backtest=lambda: True)

    def test_terminal_result_cannot_be_overwritten(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        svc = OOSLockboxService(db_path=db_path)
        lineage_id = "lin_terminal"
        svc.ensure_budget(lineage_id, total=5)

        strategy_hash = f"fixed_hash_{uuid.uuid4().hex[:8]}"
        token = PromotionToken("human_1", strategy_hash, lineage_id)
        outcome = svc.evaluate(token, run_oos_backtest=lambda: True)
        assert outcome == OOSOutcome.PASS

        # Attempting to re-evaluate the same strategy_hash raises
        # AlreadyEvaluatedError -- terminal result is immutable.
        token_dup = PromotionToken("human_2", strategy_hash, lineage_id)
        with pytest.raises(AlreadyEvaluatedError):
            svc.evaluate(token_dup, run_oos_backtest=lambda: False)

    def test_different_strategies_consume_same_lineage_budget(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        svc = OOSLockboxService(db_path=db_path)
        lineage_id = "lin_shared"
        svc.ensure_budget(lineage_id, total=3)

        for i in range(3):
            token = PromotionToken("human", f"strat_{i}_{uuid.uuid4().hex[:6]}", lineage_id)
            svc.evaluate(token, run_oos_backtest=lambda: True)

        assert svc.remaining_budget(lineage_id) == 0


# ===========================================================================
# Test 6: Numeric scan on realistic LLM-like output
# ===========================================================================


class _NumericScanGate(Gate):
    """Test gate: scans text for raw numeric values that might indicate
    data leakage from an LLM producing strategy descriptions.

    If the text contains numbers that look like backtest metrics
    (e.g., "Sharpe ratio of 1.5" or "25% return"), the scan fails.
    Pure qualitative text passes.
    """

    gate_id = "numeric_scan"
    gate_version = 1
    cost_rank = 1
    severity = GateSeverity.HARD

    # Matches: integers or floats optionally followed by %.
    _NUMERIC_PATTERN = re.compile(r"\b\d+\.?\d*%?\b")

    def check(self, ctx: GateContext) -> GateResult:
        text = ctx.metrics.get("llm_text", "")
        if not text:
            return self._pass(details={"reason": "no text to scan"})

        matches = self._NUMERIC_PATTERN.findall(text)
        if matches:
            return self._fail(
                value=float(len(matches)),
                details={
                    "reason": "numeric values found in LLM output",
                    "found": matches,
                },
            )
        return self._pass(details={"reason": "text is clean"})


class TestNumericScanOnLLMOutput:
    """Verify that a numeric-scan gate catches leaked numbers in
    LLM-like strategy descriptions."""

    def test_llm_output_with_numbers_fails(self):
        """Text containing numbers (metrics) triggers the scan."""
        text = "The strategy achieved a Sharpe ratio of 1.5 with 25% return"
        ctx = _make_gate_context(
            metrics={"llm_text": text, "n_trades": 100, "sharpe_annual": 1.0,
                     "total_return": 0.2, "exposure_time": 0.5},
        )
        gate = _NumericScanGate()
        result = gate.check(ctx)
        assert result.status == GateStatus.FAIL
        found = result.details.get("details", {}).get("found", result.details.get("found", []))
        assert len(found) > 0
        # Should have caught "1.5", "25%"
        assert any("1.5" in m for m in found)
        assert any("25" in m for m in found)

    def test_clean_llm_output_passes(self):
        """Purely qualitative text passes the scan."""
        text = "The strategy shows strong momentum characteristics"
        ctx = _make_gate_context(
            metrics={"llm_text": text, "n_trades": 100, "sharpe_annual": 1.0,
                     "total_return": 0.2, "exposure_time": 0.5},
        )
        gate = _NumericScanGate()
        result = gate.check(ctx)
        assert result.passed
        assert result.details.get("details", {}).get("reason") == "text is clean"

    def test_scan_integrated_in_pipeline(self):
        """The scan gate works within a GatePipeline alongside real gates."""
        text_with_numbers = "Return was 42% with drawdown of 8.5%"
        ctx = _make_gate_context(
            metrics={"llm_text": text_with_numbers, "n_trades": 100,
                     "sharpe_annual": 1.2, "total_return": 0.35,
                     "exposure_time": 0.55},
        )
        pipeline = GatePipeline([
            _NumericScanGate(),       # cost_rank=1 -> FAIL (hard)
            SpecValidationGate(),     # cost_rank=0 -> runs first
            PerformanceFloorGate(),   # cost_rank=5 -> NOT_EVALUATED
        ])

        report = pipeline.evaluate(ctx)
        # SpecValidation (rank 0) runs first and passes.
        # NumericScan (rank 1) runs second and fails hard.
        # PerformanceFloor (rank 5) is short-circuited.
        assert report.passed is False
        assert report.first_failed_gate == "numeric_scan"
        assert report.results[0].status == GateStatus.PASS      # spec_validation
        assert report.results[1].status == GateStatus.FAIL       # numeric_scan
        assert report.results[2].status == GateStatus.NOT_EVALUATED  # performance_floor


# ===========================================================================
# Test 7: Full definition -> hash -> snapshot -> gate chain
# ===========================================================================


class TestFullDefinitionHashSnapshotGateChain:
    """Verify the complete flow from strategy definition through data
    snapshot to run spec, checking hash determinism and independence."""

    def test_hashes_are_deterministic(self):
        """Creating the same objects twice produces identical hashes."""
        defn1 = _make_strategy_definition()
        defn2 = _make_strategy_definition()
        assert defn1.strategy_hash == defn2.strategy_hash

        df = _make_ohlcv(100, seed=42)
        hash1 = compute_data_snapshot_hash(df)
        hash2 = compute_data_snapshot_hash(df)
        assert hash1 == hash2

        rs1 = _make_run_spec(defn1.strategy_hash, data_snapshot_hash=hash1)
        rs2 = _make_run_spec(defn2.strategy_hash, data_snapshot_hash=hash2)
        assert rs1.run_spec_hash == rs2.run_spec_hash

    def test_changing_param_changes_strategy_hash_not_data_hash(self):
        """A parameter change alters strategy_hash but NOT data_snapshot_hash."""
        defn_a = _make_strategy_definition(params={"fast_period": 10, "slow_period": 30})
        defn_b = _make_strategy_definition(params={"fast_period": 15, "slow_period": 30})

        assert defn_a.strategy_hash != defn_b.strategy_hash

        # Data snapshot is independent of strategy params.
        df = _make_ohlcv(100, seed=42)
        data_hash = compute_data_snapshot_hash(df)

        # RunSpecs with different strategy hashes but same data produce different run_spec hashes.
        rs_a = _make_run_spec(defn_a.strategy_hash, data_snapshot_hash=data_hash)
        rs_b = _make_run_spec(defn_b.strategy_hash, data_snapshot_hash=data_hash)
        assert rs_a.run_spec_hash != rs_b.run_spec_hash

    def test_changing_data_changes_data_hash_not_strategy_hash(self):
        """A data change alters data_snapshot_hash but NOT strategy_hash."""
        defn = _make_strategy_definition()
        hash_before = defn.strategy_hash

        df1 = _make_ohlcv(100, seed=42)
        df2 = _make_ohlcv(100, seed=99)  # different seed = different data

        data_hash1 = compute_data_snapshot_hash(df1)
        data_hash2 = compute_data_snapshot_hash(df2)
        assert data_hash1 != data_hash2

        # Strategy hash unchanged.
        assert defn.strategy_hash == hash_before

    def test_data_snapshot_object_creation(self):
        """DataSnapshot captures metadata about the OHLCV data."""
        df = _make_ohlcv(200, seed=42)
        snapshot = DataSnapshot(
            snapshot_hash=compute_data_snapshot_hash(df),
            security_id="AAPL",
            provider="yfinance",
            window_start="2018-01-02",
            window_end="2018-10-09",
            n_bars=len(df),
            df=df,
        )
        assert len(snapshot.snapshot_hash) == 64
        assert snapshot.n_bars == 200
        assert snapshot.security_id == "AAPL"

    def test_full_chain_definition_to_registry(self, registry, registry_session):
        """Full chain: definition -> snapshot -> runspec -> registry -> gate."""
        # Create definition.
        defn = _make_strategy_definition()

        # Create data snapshot.
        df = _make_ohlcv(252, seed=42, drift=0.0004)
        data_hash = compute_data_snapshot_hash(df)

        # Create RunSpec tying them together.
        run_spec = _make_run_spec(defn.strategy_hash, data_snapshot_hash=data_hash)

        # Register in the registry.
        registry.register_strategy(
            definition_json=defn.model_dump_json(),
            strategy_hash=defn.strategy_hash,
            template_id=defn.template_id,
            template_version=defn.template_version,
            template_hash=defn.template_hash,
            security_id=defn.security_id,
            cost_profile_id=defn.cost_profile_id,
            cost_profile_hash=defn.cost_profile_hash,
            strategy_family=defn.strategy_family,
        )
        registry.register_run_spec(
            run_spec_json=run_spec.model_dump_json(),
            run_spec_hash=run_spec.run_spec_hash,
            strategy_hash=defn.strategy_hash,
            evaluation_role=run_spec.evaluation_role.value,
            window_start=str(run_spec.window_start),
            window_end=str(run_spec.window_end),
            data_snapshot_hash=data_hash,
        )
        run_id = registry.register_run(
            run_spec_hash=run_spec.run_spec_hash,
            strategy_hash=defn.strategy_hash,
        )
        registry.append_event(run_id, EventType.RUN_QUEUED)
        registry.append_event(run_id, EventType.RUN_STARTED)
        registry.append_event(run_id, EventType.RUN_COMPLETED)
        registry_session.commit()

        # Compute benchmark.
        bm = compute_buy_hold(df)

        # Build gate context from the "result".
        rng = np.random.default_rng(42)
        strategy_returns = rng.normal(0.0005, 0.012, 252)
        ctx = GateContext(
            metrics={
                "n_trades": 80,
                "sharpe_annual": 1.1,
                "total_return": 0.28,
                "max_drawdown": -0.10,
                "exposure_time": 0.50,
            },
            trades=[],
            returns=strategy_returns,
            equity_curve=[10000 + i * 12 for i in range(252)],
            strategy_hash=defn.strategy_hash,
            template_id=defn.template_id,
            benchmark={
                "buy_hold_sharpe": bm.annualized_sharpe,
                "buy_hold_return": bm.total_return,
                "buy_hold_max_drawdown": bm.max_drawdown,
            },
        )

        # Run the full gate pipeline.
        pipeline = GatePipeline([
            SpecValidationGate(),
            MinimumActivityGate(),
            PerformanceFloorGate(),
            BenchmarkRelativeGate(),
        ])
        report = pipeline.evaluate(ctx)

        # Verify the report is well-formed and all gates ran.
        assert len(report.results) == 4
        assert all(r.status != GateStatus.ERROR for r in report.results)
        # SpecValidation and MinimumActivity should pass on these inputs.
        assert report.results[0].passed  # spec_validation
        assert report.results[1].passed  # minimum_activity

        # Verify the status is still COMPLETED in the registry.
        assert registry.get_current_status(run_id) == EventType.RUN_COMPLETED
