"""Paper/Live monitoring — compare actual trading performance to backtest expectations."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PerformanceDrift:
    metric: str
    backtest_value: float | None
    live_value: float | None
    delta: float | None
    severity: str  # ok, warning, critical


@dataclass
class MonitoringReport:
    agent_id: int
    trial_id: int | None
    drifts: list[PerformanceDrift]
    overall_status: str  # healthy, warning, critical
    summary: str


async def compare_live_to_backtest(
    agent_config_id: int,
    trial_id: int | None = None,
) -> MonitoringReport:
    """Compare live/paper trading results to backtest expectations.

    Args:
        agent_config_id: The agent to monitor.
        trial_id: Optional backtest trial to compare against.

    Returns:
        MonitoringReport with drift analysis.
    """
    from src.backend.db.engine import async_session
    from src.backend.db.models import TradeDB, AgentConfigDB
    from sqlalchemy import select

    drifts: list[PerformanceDrift] = []

    async with async_session() as session:
        # Get agent info
        agent = await session.execute(
            select(AgentConfigDB).where(AgentConfigDB.id == agent_config_id)
        )
        agent_row = agent.scalar_one_or_none()
        if agent_row is None:
            return MonitoringReport(
                agent_id=agent_config_id, trial_id=trial_id,
                drifts=[], overall_status="unknown", summary="Agent not found",
            )

        # Get live trades
        trades = await session.execute(
            select(TradeDB)
            .where(TradeDB.agent_config_id == agent_config_id)
            .order_by(TradeDB.submitted_at.desc())
        )
        live_trades = list(trades.scalars().all())

    if not live_trades:
        return MonitoringReport(
            agent_id=agent_config_id, trial_id=trial_id,
            drifts=[], overall_status="no_data",
            summary=f"No live trades found for agent {agent_config_id}",
        )

    # Compute live metrics
    live_pnl = sum(
        float(t.avg_fill_price or 0) * float(t.filled_quantity or 0) * (1 if t.side == "SELL" else -1)
        for t in live_trades
    )
    live_trade_count = len(live_trades)
    live_wins = sum(1 for t in live_trades if t.side == "SELL" and t.avg_fill_price and t.avg_fill_price > 0)
    live_win_rate = live_wins / max(live_trade_count, 1)

    # Compare to backtest if trial given
    if trial_id:
        from src.backend.backtesting.results.store import ResultStore
        store = ResultStore()
        bt = store.get_trial(trial_id)
        if bt:
            if bt.win_rate is not None:
                delta_wr = live_win_rate - bt.win_rate
                sev = "ok" if abs(delta_wr) < 0.1 else ("warning" if abs(delta_wr) < 0.2 else "critical")
                drifts.append(PerformanceDrift("win_rate", bt.win_rate, live_win_rate, round(delta_wr, 4), sev))

            if bt.trade_count and live_trade_count > 0:
                # Normalized trade frequency
                bt_freq = bt.trade_count
                live_freq = live_trade_count
                delta_freq = live_freq - bt_freq
                sev = "ok" if abs(delta_freq) < bt_freq * 0.5 else "warning"
                drifts.append(PerformanceDrift("trade_frequency", bt_freq, live_freq, delta_freq, sev))

    critical_count = sum(1 for d in drifts if d.severity == "critical")
    warning_count = sum(1 for d in drifts if d.severity == "warning")

    if critical_count > 0:
        status = "critical"
    elif warning_count > 0:
        status = "warning"
    else:
        status = "healthy"

    return MonitoringReport(
        agent_id=agent_config_id,
        trial_id=trial_id,
        drifts=drifts,
        overall_status=status,
        summary=f"{live_trade_count} live trades, PnL: ${live_pnl:.2f}, Status: {status}",
    )
