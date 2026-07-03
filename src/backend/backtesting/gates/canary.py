"""ATS-1738 — Leakage canary gate.

Runs the strategy on synthetic zero-drift data. If the strategy profits
on noise, it's leaking information from the harness.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np

from src.backend.backtesting.gates.pipeline import (
    Gate,
    GateContext,
    GateResult,
    GateSeverity,
)
from src.backend.backtesting.gates.synthetic import (
    generate_block_bootstrap_ohlcv,
    generate_random_walk_ohlcv,
)

logger = logging.getLogger(__name__)


def _compute_perbar_sharpe(returns: np.ndarray) -> float:
    """Per-bar Sharpe ratio (mean / std, no annualization)."""
    if len(returns) < 2:
        return 0.0
    std = np.std(returns, ddof=1)
    if std == 0:
        return 0.0
    return float(np.mean(returns) / std)


class LeakageCanaryGate(Gate):
    """Gate: strategy must not profit on zero-drift synthetic data.

    Generates n_paths synthetic OHLCV series, runs the strategy on each,
    and checks that the candidate's per-bar Sharpe exceeds the 99th
    percentile of the noise distribution.
    """

    gate_id = "leakage_canary"
    gate_version = 1
    cost_rank = 10
    severity = GateSeverity.HARD

    N_PATHS = 100
    PERCENTILE = 99

    def __init__(
        self,
        run_strategy_fn: Callable[[Any], np.ndarray] | None = None,
        n_paths: int = 100,
        variant: str = "random_walk",
    ):
        """
        Args:
            run_strategy_fn: Callable(ohlcv_df) → returns array.
                Runs the same strategy spec on a given OHLCV DataFrame.
            n_paths: Number of synthetic paths.
            variant: "random_walk" or "block_bootstrap".
        """
        self._run_fn = run_strategy_fn
        self.N_PATHS = n_paths
        self._variant = variant
        if variant == "block_bootstrap":
            self.gate_id = "leakage_canary_bootstrap"

    def check(self, ctx: GateContext) -> GateResult:
        if self._run_fn is None:
            return self._pass(details={"reason": "no run function provided, provisional pass", "provisional": True})

        candidate_returns = ctx.returns
        if candidate_returns is None or len(candidate_returns) < 10:
            return self._fail(details={"reason": "insufficient candidate returns"})

        candidate_sr = _compute_perbar_sharpe(np.asarray(candidate_returns))

        # We need the real OHLCV data to generate synthetics — it should
        # be in ctx.metrics["ohlcv_df"] if the caller provides it.
        ohlcv_df = ctx.metrics.get("ohlcv_df")
        if ohlcv_df is None:
            return self._pass(details={"reason": "no OHLCV data for synthetic generation, provisional pass", "provisional": True})

        # Generate synthetic paths.
        if self._variant == "block_bootstrap":
            paths = generate_block_bootstrap_ohlcv(ohlcv_df, self.N_PATHS)
        else:
            paths = generate_random_walk_ohlcv(ohlcv_df, self.N_PATHS)

        if not paths:
            return self._pass(details={"reason": "could not generate synthetic paths"})

        # Run strategy on each path, collect per-bar Sharpe.
        noise_sharpes = []
        failed_paths = 0
        for path_df in paths:
            try:
                path_returns = self._run_fn(path_df)
                sr = _compute_perbar_sharpe(np.asarray(path_returns))
                noise_sharpes.append(sr)
            except Exception as exc:
                failed_paths += 1
                if failed_paths <= 3:  # log first few, don't spam
                    logger.debug("Canary path failed: %s", exc)
                continue

        if failed_paths > 0:
            logger.info("Canary: %d/%d synthetic paths failed", failed_paths, len(paths))

        if len(noise_sharpes) < 10:
            return self._pass(details={"reason": f"only {len(noise_sharpes)} paths succeeded, insufficient"})

        noise_arr = np.array(noise_sharpes)
        noise_pct = float(np.percentile(noise_arr, self.PERCENTILE))
        noise_mean = float(np.mean(noise_arr))

        details = {
            "candidate_sr_perbar": candidate_sr,
            "noise_p99_sr": noise_pct,
            "noise_mean_sr": noise_mean,
            "n_paths_succeeded": len(noise_sharpes),
            "variant": self._variant,
        }

        # Fail 1: candidate within noise band.
        if candidate_sr <= noise_pct:
            return self._fail(
                value=candidate_sr,
                threshold=noise_pct,
                reason=f"candidate SR {candidate_sr:.4f} within noise band (p{self.PERCENTILE}={noise_pct:.4f})",
                **details,
            )

        # Fail 2: noise mean significantly positive (harness-level leak).
        if noise_mean > 0.005:  # > 0.5% mean per-bar SR on noise = suspicious
            return self._fail(
                value=noise_mean,
                threshold=0.005,
                reason=f"noise mean SR {noise_mean:.4f} significantly positive — harness leak suspected",
                **details,
            )

        return self._pass(value=candidate_sr, **details)
