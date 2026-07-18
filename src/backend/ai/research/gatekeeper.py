"""Gap 2: ResearchGatekeeper — assembles and wraps the default gate pipeline.

Translates between the research loop's evaluate(metrics, returns, context) call
and the gate pipeline's evaluate(GateContext) interface.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.backend.backtesting.gates.basic_gates import (
    BenchmarkRelativeGate,
    DataIntegrityGate,
    MinimumActivityGate,
    PerformanceFloorGate,
    ProviderCapabilityGate,
    SpecValidationGate,
)
from src.backend.backtesting.gates.canary import LeakageCanaryGate
from src.backend.backtesting.gates.cost_stress_gate import CostStressGate
from src.backend.backtesting.gates.deflated_sharpe import DeflatedSharpeGate
from src.backend.backtesting.gates.lag_gate import LagFragilityGate
from src.backend.backtesting.gates.pipeline import GateContext, GatePipeline, GateSeverity


# F1 — Rigor presets: named bundles of gate thresholds, applied in place over the
# hardcoded class constants. These presets are the SINGLE SOURCE OF TRUTH for effective gate
# thresholds (H4: the old config/gates.default.yaml was never loaded and diverged by ~10x — deleted).
# The `min_trades` values are CALIBRATED from the observed daily-bar trade-count distribution
# (median ~12; the old hardcoded 50 passed 0%).
# `min_trades` = the smart-activity FLOOR (statistical minimum, df>=4); `activity_t` = the per-trade edge t*.
# DATA-BACKED by SMART-ACTIVITY-CALIBRATION.md (226 rule_based t-stats): activity_t 1.0/1.65/2.33 → sensible
# monotonic pass rates 34.5/12.4/4.4%; floor >= 5 (exploratory raised 3→5 — a t-stat on <5 trades is meaningless).
# `min_stressed_sharpe` (M20) must be <= `min_sharpe` per preset, else the un-preset 0.5 cost-stress floor
# makes the sub-0.5 exploratory tier structurally unreachable.
RIGOR_PRESETS: dict[str, dict[str, float]] = {
    "exploratory": {"min_trades": 5, "activity_t": 1.0,  "min_sharpe": 0.3, "min_stressed_sharpe": 0.2, "dsr_threshold": 0.90, "cost_multiplier": 1.5, "benchmark_sharpe_min": 0.1},
    "standard":    {"min_trades": 5, "activity_t": 1.65, "min_sharpe": 0.5, "min_stressed_sharpe": 0.4, "dsr_threshold": 0.95, "cost_multiplier": 2.0, "benchmark_sharpe_min": 0.2},
    "strict":      {"min_trades": 8, "activity_t": 2.33, "min_sharpe": 0.8, "min_stressed_sharpe": 0.6, "dsr_threshold": 0.95, "cost_multiplier": 3.0, "benchmark_sharpe_min": 0.3},
}


def build_default_pipeline(rigor: dict[str, float] | None = None, mode: str = "robustness",
                           soft_dsr: bool = False) -> GatePipeline:
    """Assemble the default gate pipeline. `rigor` (a preset bundle) overrides the
    relevant gate thresholds in place — instance attributes shadow the class constants
    (F1: the allowed finetune that makes the Rigor preset bind). `mode="regime"` flips the
    smart-activity gate to label-mode (thin-but-above-floor → low-confidence pass, P1 Chunk C)."""
    r = rigor or {}
    min_act = MinimumActivityGate()
    if mode == "regime":
        min_act.adaptive_mode = "label"   # surface thin regime ideas (low-confidence), don't kill them
    perf = PerformanceFloorGate()
    bench = BenchmarkRelativeGate()
    cost = CostStressGate()
    dsr = DeflatedSharpeGate()
    if "min_trades" in r:
        min_act.MIN_TRADES = r["min_trades"]
    if "activity_t" in r:
        min_act.ACTIVITY_T = r["activity_t"]   # switches on the smart-activity adaptive layer
    if "min_sharpe" in r:
        perf.MIN_SHARPE = r["min_sharpe"]
    if "benchmark_sharpe_min" in r:
        bench.SHARPE_IMPROVEMENT_MIN = r["benchmark_sharpe_min"]
    if "cost_multiplier" in r:
        cost.COST_MULTIPLIER = r["cost_multiplier"]
    if "min_stressed_sharpe" in r:
        cost.MIN_STRESSED_SHARPE = r["min_stressed_sharpe"]   # M20: bind the cost-stress floor to the tier
    if "dsr_threshold" in r:
        dsr.THRESHOLD = r["dsr_threshold"]
    lag = LagFragilityGate()
    # M22: the leakage canary runs LAST (cost_rank 10 → only on survivors of the cheaper gates) and is
    # SOFT — it surfaces suspected look-ahead / harness leakage as a strong weakness rather than
    # hard-blocking, since the "candidate within noise band" arm can false-positive a weak-but-real edge.
    # It stays inert (provisional pass, no cost) until the loop supplies a run_strategy_fn via the context.
    canary = LeakageCanaryGate(n_paths=50)
    canary.severity = GateSeverity.SOFT
    if mode == "regime":
        # Idea-surfacing: the QUALITY gates go SOFT (a FAIL is recorded as a weakness, non-fatal, no
        # short-circuit — the pipeline already treats SOFT fails this way). Integrity gates + the activity
        # floor + benchmark_relative (the anti-garbage / not-dominated floor) stay HARD.
        # DSR stays HARD too (safety pass 2026-07-16, reconciled plan §2c): multiplicity control is an
        # integrity gate, and regime mode runs with the robustness OOS disabled — softening DSR while the
        # OOS backstop is off was a pure loosening.
        for _g in (perf, cost, lag):
            _g.severity = GateSeverity.SOFT
    elif soft_dsr:
        # RT2 (Track 7, FB4-gated): the advisory stage-1. A DSR FAIL becomes a recorded WEAKNESS
        # ("could be luck") instead of an execution — the candidate proceeds to the OOS lockbox,
        # whose FB4 campaign ledger caps the fresh-data spend and Šidák-raises the per-test bar
        # with every terminal verdict. The caller (run.py) enforces the guard: soft_dsr is only
        # honored in robustness mode WITH the lockbox enabled (the FB4-controlled backstop).
        dsr.severity = GateSeverity.SOFT
    return GatePipeline([
        SpecValidationGate(),
        ProviderCapabilityGate(),
        DataIntegrityGate(),
        min_act,
        perf,
        bench,
        cost,
        lag,
        dsr,
        canary,
    ])


class ResearchGatekeeper:
    """Wraps GatePipeline for the research loop protocol."""

    def __init__(
        self,
        n_trials_global: int = 0,
        trial_sr_variance: float = 0.001,
        rigor: str = "standard",
        mode: str = "robustness",
        soft_dsr: bool = False,
    ):
        self.pipeline = build_default_pipeline(RIGOR_PRESETS.get(rigor, RIGOR_PRESETS["standard"]),
                                               mode=mode, soft_dsr=soft_dsr)
        self.n_trials_global = n_trials_global
        self.trial_sr_variance = trial_sr_variance
        self.trial_sr_variance_defaulted = False
        self.trial_median_t = 0.0
        self.search_size = 0

    def update_registry_stats(
        self, n_trials: int, sr_variance: float, *, variance_defaulted: bool = False,
        trial_median_t: float = 0.0, search_size: int = 0,
    ) -> None:
        """Update DSR inputs from the registry (M24: carry an explicit defaulted flag rather than
        letting downstream sniff the magic floor value). PF4: a MEASURED 0.0 (perfectly clustered
        trials) passes through un-defaulted — the gate's null-variance floor sets the bar and the
        verdict stays firm; only a genuinely unmeasured variance gets the 0.001 default."""
        self.n_trials_global = n_trials
        if variance_defaulted or sr_variance < 0.0:
            self.trial_sr_variance = 0.001
            self.trial_sr_variance_defaulted = True
        else:
            self.trial_sr_variance = sr_variance
            self.trial_sr_variance_defaulted = False
        self.trial_median_t = float(trial_median_t or 0.0)
        self.search_size = int(search_size or 0)   # B4: sr0-only multiplicity (0 = per-run)

    def evaluate(
        self,
        metrics: dict[str, Any],
        returns: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the full gate pipeline.

        Args:
            metrics: Flat metrics dict from executor.
            returns: numpy array of per-bar returns.
            context: Additional context (strategy_hash, bias_flags, benchmark).

        Returns:
            Dict with "passed", "first_failed_gate", "results" list.
        """
        benchmark = context.get("benchmark", {})
        if not benchmark and "buy_hold_return" in metrics:
            benchmark = {
                "buy_hold_return": metrics.get("buy_hold_return", 0.0),
                "buy_hold_sharpe": metrics.get("buy_hold_sharpe", 0.0),
                "buy_hold_max_drawdown": metrics.get("buy_hold_max_drawdown", 0.0),
            }

        ctx = GateContext(
            metrics={
                "n_trades": metrics.get("n_trades", 0),
                "sharpe_annual": metrics.get("sharpe_annual", 0.0),
                "lagged_sharpe_annual": metrics.get("lagged_sharpe_annual"),  # M23: producer wired (None → provisional)
                "total_return": metrics.get("total_return", 0.0),
                "max_drawdown": metrics.get("max_drawdown", 0.0),
                "exposure_time": metrics.get("exposure_time", 0.0),
                "commission": metrics.get("commission", 0.001),
                "trade_returns": metrics.get("trade_returns", []),   # smart-activity per-trade edge
                "ohlcv_df": metrics.get("ohlcv_df"),                 # M22: real OHLCV for canary synthetics
            },
            trades=[],
            returns=np.asarray(returns) if returns is not None else np.array([]),
            equity_curve=metrics.get("equity_curve", []),
            strategy_hash=context.get("strategy_hash", ""),
            template_id=context.get("template_id", ""),
            params=metrics.get("params", {}),
            security_id=context.get("security_id", ""),
            bias_flags=context.get("bias_flags", {}),
            benchmark=benchmark,
            n_trials_global=self.n_trials_global,
            trial_sr_variance=self.trial_sr_variance,
            trial_sr_variance_defaulted=self.trial_sr_variance_defaulted,
            trial_median_t=self.trial_median_t,
            search_size=self.search_size,
            run_strategy_fn=context.get("run_strategy_fn"),          # M22: supplied per-candidate by the loop
        )

        report = self.pipeline.evaluate(ctx)

        return {
            "passed": report.passed,
            "first_failed_gate": report.first_failed_gate,
            "errored_gate": report.errored_gate,   # M21 (review): surface the errored-hard-gate cause
            "results": [
                {
                    "gate_id": r.gate_id,
                    "status": str(r.status),
                    "value": r.value,
                    "threshold": r.threshold,
                    "severity": str(r.severity),
                    "details": r.details,
                }
                for r in report.results
            ],
        }
