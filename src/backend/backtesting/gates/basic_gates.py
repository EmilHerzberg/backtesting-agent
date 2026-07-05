"""ATS-1727 — Gates 0-5: cheap triage gates.

Gate 0: StrategyDefinition validation
Gate 1: RunSpec validation (placeholder — validated at creation time)
Gate 2: Provider capability (bias flags)
Gate 3: Data integrity (OHLCV consistency)
Gate 4: Minimum activity (trade count + exposure)
Gate 5: Performance floor (Sharpe + return)
"""

from __future__ import annotations

import logging

import numpy as np

from src.backend.backtesting.gates.pipeline import (
    Gate,
    GateContext,
    GateResult,
    GateSeverity,
)

logger = logging.getLogger(__name__)


def per_trade_t(trade_returns) -> float:
    """Per-trade edge t-stat: mean/std(ddof=1)·√N (N = trades = the independent bets).

    Shared by the MinimumActivityGate (selection) and the regime P2 hold-out (validation) so
    "significant" means the same thing in both. Mirrors the identical-trades edge case. Returns
    0.0 for < 2 trades (no computable t).
    """
    a = np.asarray(trade_returns, dtype=np.float64)
    if a.size < 2:
        return 0.0
    mean = float(a.mean())
    std = float(a.std(ddof=1))
    if std > 0:
        return float(mean / std * (a.size ** 0.5))
    return 99.0 if mean > 0 else 0.0  # identical trades: clear pass if positive, else no edge


class SpecValidationGate(Gate):
    """Gate 0: Reject malformed or empty strategy specs."""

    gate_id = "spec_validation"
    gate_version = 1
    cost_rank = 0
    severity = GateSeverity.HARD

    def check(self, ctx: GateContext) -> GateResult:
        if not ctx.strategy_hash:
            return self._fail(reason="strategy_hash is empty")
        if not ctx.template_id:
            return self._fail(reason="template_id is empty")
        return self._pass()


class ProviderCapabilityGate(Gate):
    """Gate 2: Flag research conclusions built on biased/prototype data.

    H24: a SOFT gate — survivorship-biased free providers (the default yfinance included) are
    usable for exploration, so this surfaces the risk as a weakness rather than hard-blocking every
    default run. The FAIL is recorded (and caps the "research conclusion" claim downstream) but does
    not short-circuit the pipeline. Callers that want a hard block can raise the severity.
    """

    gate_id = "provider_capability"
    gate_version = 2
    cost_rank = 2
    severity = GateSeverity.SOFT

    def check(self, ctx: GateContext) -> GateResult:
        flags = ctx.bias_flags
        if not flags:
            return self._pass(reason="no bias flags available")

        if flags.get("survivorship_bias", False):
            return self._fail(
                reason="data has survivorship bias risk — not a research-grade conclusion",
                research_conclusion_allowed=flags.get("research_conclusion_allowed", False),
            )
        return self._pass()


class DataIntegrityGate(Gate):
    """Gate 3: OHLCV consistency checks."""

    gate_id = "data_integrity"
    gate_version = 1
    cost_rank = 3
    severity = GateSeverity.HARD

    MAX_SINGLE_BAR_JUMP = 0.5  # 50% single-bar price change threshold

    def check(self, ctx: GateContext) -> GateResult:
        metrics = ctx.metrics
        # If we have raw OHLCV data stats, check them.
        # For now check via metrics that were computed during the run.
        n_trades = metrics.get("n_trades", 0)

        # Check for impossible returns if we have the returns series.
        returns = ctx.returns
        if returns is not None and hasattr(returns, '__len__') and len(returns) > 0:
            max_abs_return = float(np.max(np.abs(returns)))
            if max_abs_return > self.MAX_SINGLE_BAR_JUMP:
                return self._fail(
                    value=max_abs_return,
                    threshold=self.MAX_SINGLE_BAR_JUMP,
                    reason=f"single-bar return {max_abs_return:.2%} exceeds {self.MAX_SINGLE_BAR_JUMP:.0%} threshold",
                )

        return self._pass()


class MinimumActivityGate(Gate):
    """Gate 4: statistical sample-adequacy of the per-trade edge (smart-activity).

    Floor (hard, anti-luck) → exposure sanity → adaptive per-trade edge t-stat.
    See SMART-ACTIVITY-GATE-SPEC. ``ACTIVITY_T=None`` (default) or <2 trade returns
    → floor-only (back-compat for non-research callers). ``adaptive_mode="label"``
    (regime forward-compat, set elsewhere) turns the adaptive kill into a
    low-confidence pass.
    """

    gate_id = "minimum_activity"
    gate_version = 2
    cost_rank = 4
    severity = GateSeverity.HARD

    MIN_TRADES = 50          # hard floor (statistical minimum); rigor presets lower it
    MIN_EXPOSURE = 0.05
    MAX_EXPOSURE = 0.95
    ACTIVITY_T = None        # per-trade edge t* (set by rigor preset); None → floor-only
    adaptive_mode = "kill"   # "kill" (default) | "label" (regime forward-compat, XR-1)

    def check(self, ctx: GateContext) -> GateResult:
        n_trades = int(ctx.metrics.get("n_trades", 0))
        exposure = ctx.metrics.get("exposure_time", 0.0)
        tr = ctx.metrics.get("trade_returns")           # N2: avoid numpy-array truthiness ambiguity
        if tr is None:
            tr = []

        # Hard floor — below it no t-stat is trustworthy (tiny-N + fat tails). Kill regardless.
        if n_trades < self.MIN_TRADES:
            return self._fail(value=float(n_trades), threshold=float(self.MIN_TRADES),
                              reason=f"{n_trades} trades < floor {self.MIN_TRADES}", tier="insufficient")

        # Exposure sanity (unchanged) — not always-in / never-in.
        if exposure < self.MIN_EXPOSURE or exposure > self.MAX_EXPOSURE:
            return self._fail(
                value=exposure, tier="insufficient",
                reason=f"exposure {exposure:.1%} outside [{self.MIN_EXPOSURE:.0%}, {self.MAX_EXPOSURE:.0%}]",
                min_exposure=self.MIN_EXPOSURE, max_exposure=self.MAX_EXPOSURE,
            )

        # Back-compat: non-research callers (no t*) → floor-only (old absolute-count behavior).
        if self.ACTIVITY_T is None:
            return self._pass(value=float(n_trades), tier="adequate", note="floor-only")
        # SAS-5: t* is set (research) but no per-trade returns reached the gate despite n_trades >= floor —
        # a plumbing inconsistency, NOT genuine no-data. Don't fake "adequate"; flag low-confidence + log.
        if len(tr) < 2:
            logger.warning("minimum_activity: n_trades=%d >= floor but trade_returns empty (plumbing?)", n_trades)
            return self._pass(value=float(n_trades), tier="adequate", low_confidence=True,
                              note="plumbing_inconsistency")

        # Adaptive per-trade edge t-stat (N = trades = the independent bets). Shared helper (P2 reuses it).
        t_raw = per_trade_t(tr)
        t = round(float(t_raw), 3)  # display value; compare on the raw t (N1)

        if t_raw < self.ACTIVITY_T:
            if self.adaptive_mode == "label":
                return self._pass(value=t, tier="thin", low_confidence=True, t_stat=t, n_trades=n_trades)
            return self._fail(value=t, threshold=float(self.ACTIVITY_T), tier="thin", n_trades=n_trades,
                              reason=f"per-trade edge t={t} < t*={self.ACTIVITY_T}")
        return self._pass(value=t, tier="adequate", t_stat=t, n_trades=n_trades)


class PerformanceFloorGate(Gate):
    """Gate 5: Minimum Sharpe and positive return."""

    gate_id = "performance_floor"
    gate_version = 1
    cost_rank = 5
    severity = GateSeverity.HARD

    MIN_SHARPE = 0.5
    MIN_RETURN = 0.0

    def check(self, ctx: GateContext) -> GateResult:
        sharpe = ctx.metrics.get("sharpe_annual", 0.0)
        total_return = ctx.metrics.get("total_return", 0.0)

        if sharpe < self.MIN_SHARPE:
            return self._fail(
                value=sharpe,
                threshold=self.MIN_SHARPE,
                reason=f"Sharpe {sharpe:.2f} below floor {self.MIN_SHARPE}",
            )

        if total_return <= self.MIN_RETURN:
            return self._fail(
                value=total_return,
                threshold=self.MIN_RETURN,
                reason=f"total return {total_return:.2%} not positive",
            )

        return self._pass(value=sharpe)


class BenchmarkRelativeGate(Gate):
    """Gate 6: Strategy must beat buy-and-hold on at least one dimension."""

    gate_id = "benchmark_relative"
    gate_version = 1
    cost_rank = 6
    severity = GateSeverity.HARD

    SHARPE_IMPROVEMENT_MIN = 0.2
    DD_IMPROVEMENT_MIN = 0.20  # 20% drawdown improvement
    RETURN_SACRIFICE_MAX = 0.30  # max 30% return sacrifice for DD improvement

    def check(self, ctx: GateContext) -> GateResult:
        bm = ctx.benchmark
        if not bm:
            return self._pass(reason="no benchmark available, skipping")

        strategy_sharpe = ctx.metrics.get("sharpe_annual", 0.0)
        strategy_return = ctx.metrics.get("total_return", 0.0)
        strategy_dd = ctx.metrics.get("max_drawdown", 0.0)

        bh_sharpe = bm.get("buy_hold_sharpe", 0.0)
        bh_return = bm.get("buy_hold_return", 0.0)
        bh_dd = bm.get("buy_hold_max_drawdown", 0.0)

        # Path A: Sharpe improvement
        sharpe_improvement = strategy_sharpe - bh_sharpe
        path_a = sharpe_improvement >= self.SHARPE_IMPROVEMENT_MIN

        # Path B: Drawdown improvement without excessive return sacrifice
        dd_improvement = abs(strategy_dd) - abs(bh_dd)  # negative = better
        return_sacrifice = (bh_return - strategy_return) / max(abs(bh_return), 1e-9)
        path_b = (
            dd_improvement < -self.DD_IMPROVEMENT_MIN * abs(bh_dd)
            and return_sacrifice < self.RETURN_SACRIFICE_MAX
        ) if bh_dd != 0 else False

        # Path C: risk-aware excess return (M19). Positive raw excess ALONE is vacuous — a strategy
        # that beats buy-and-hold on return while taking a WORSE risk-adjusted profile (lower Sharpe)
        # is not real outperformance. Require positive excess AND no Sharpe degradation vs the
        # benchmark, so the `benchmark_sharpe_min` (Path A) knob can still bind for the top tier.
        excess_return = strategy_return - bh_return
        path_c = excess_return > 0 and sharpe_improvement >= 0

        if path_a or path_b or path_c:
            return self._pass(
                value=sharpe_improvement,
                path_a_sharpe=path_a,
                path_b_drawdown=path_b,
                path_c_excess_return=path_c,
                sharpe_improvement=sharpe_improvement,
                excess_return=excess_return,
            )

        return self._fail(
            value=sharpe_improvement,
            reason="strategy does not beat buy-and-hold on any dimension",
            path_a_sharpe=path_a,
            path_b_drawdown=path_b,
            path_c_excess_return=path_c,
        )
