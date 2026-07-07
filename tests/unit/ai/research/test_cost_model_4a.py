"""Phase 4 / cluster 4A — unified cost model (H29 / M55).

The AI research executor charged a bare 0.1% commission (10 bps/side) while the CLI charged the full
commission + half-spread + slippage (~14.5 bps/side), so AI-discovered strategies were graded ~30%
cheaper than the platform's documented cost model. Both paths now derive the effective cost from one
shared helper, exposed as run/request params.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.backend.backtesting.costs.model import effective_commission_pct

# (async test runs under asyncio_mode=auto; no module-wide mark so the sync test stays sync)


@pytest.mark.finding("H29")
def test_effective_commission_matches_cli_formula():
    # 0.1% commission + 2.5 bps half-spread + 2 bps slippage = 14.5 bps/side.
    assert effective_commission_pct(0.001, 5.0, 2.0) == pytest.approx(0.00145)
    assert effective_commission_pct() == pytest.approx(0.00145)          # realistic default
    # Independent hardcoded expectation (NOT the function body re-derived): 0.0005 + 8bps/2 + 3bps
    # = 0.0005 + 0.0004 + 0.0003 = 0.0012. (The CLI calls this same helper — no separate inline formula.)
    assert effective_commission_pct(0.0005, 8.0, 3.0) == pytest.approx(0.0012)


class _CaptureExec:
    def __init__(self, cash: float = 10_000.0, commission: float = 0.001):
        _CaptureExec.commission = commission

    def run(self, spec, data, *, warmup_bars=0):
        return {
            "sharpe_annual": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "n_trades": 0,
            "trade_returns": [], "exposure_time": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
            "buy_hold_return": 0.0, "buy_hold_sharpe": 0.0, "buy_hold_max_drawdown": 0.0,
            "returns": np.array([]), "equity_curve": [], "strategy_hash": spec.get("strategy_hash", ""),
            "template_id": spec.get("template_id", ""), "params": {}, "commission": _CaptureExec.commission,
            "ohlcv_df": data, "lagged_sharpe_annual": None,
        }


@pytest.mark.finding("H29")
async def test_run_research_charges_realistic_effective_commission(monkeypatch, frozen_ohlcv):
    import src.backend.ai.research.run as runmod

    _CaptureExec.commission = None
    monkeypatch.setattr(runmod, "ResearchExecutor", _CaptureExec)
    await runmod.run_research(
        goal="x", assets=["AAPL"], max_runs=1, target_candidates=1, agent_mode="rule_based",
        enable_oos=False, enable_leakage_canary=False, fetch_fn=frozen_ohlcv,
    )
    # The loop's executor is charged the full effective cost (14.5 bps), not the old bare 10 bps.
    assert _CaptureExec.commission == pytest.approx(0.00145)
