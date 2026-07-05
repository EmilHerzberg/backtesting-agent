"""Metrics extraction and calculation for backtest results."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# H10 / M2 — winsorization caps so no-downside / no-loss / short-window cases return a bounded value
# instead of a sentinel the optimizer chases into degenerate strategies.
_SORTINO_CAP = 10.0
_PROFIT_FACTOR_CAP = 10.0
_CALMAR_CAP = 10.0
_MIN_CALMAR_YEARS = 0.1  # M2 — min duration before annualizing (guards wild short-window CAGR)


@dataclass
class TradeDetail:
    """Detailed information about a single trade."""

    entry_time: str
    exit_time: str
    side: str  # "long" or "short"
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    duration: str


def extract_trades(stats: pd.Series) -> list[TradeDetail]:
    """Extract individual trades from backtesting.py stats._trades DataFrame.

    Args:
        stats: The ``pd.Series`` returned by ``Backtest.run()``.

    Returns:
        List of :class:`TradeDetail` objects.  Returns an empty list when
        the stats object contains no trade data.
    """
    try:
        trades_df: pd.DataFrame = stats["_trades"]
    except (KeyError, TypeError):
        return []

    if trades_df is None or trades_df.empty:
        return []

    details: list[TradeDetail] = []
    for _, row in trades_df.iterrows():
        entry_time = str(row.get("EntryTime", ""))
        exit_time = str(row.get("ExitTime", ""))
        size = float(row.get("Size", 0))
        side = "long" if size > 0 else "short"
        entry_price = float(row.get("EntryPrice", 0.0))
        exit_price = float(row.get("ExitPrice", 0.0))
        pnl = float(row.get("PnL", 0.0))

        # PnL percentage relative to entry value
        entry_value = abs(size) * entry_price
        pnl_pct = (pnl / entry_value * 100) if entry_value != 0 else 0.0

        # Duration
        try:
            dur = pd.Timestamp(exit_time) - pd.Timestamp(entry_time)
            duration = str(dur)
        except Exception:
            duration = ""

        details.append(
            TradeDetail(
                entry_time=entry_time,
                exit_time=exit_time,
                side=side,
                entry_price=entry_price,
                exit_price=exit_price,
                size=abs(size),
                pnl=pnl,
                pnl_pct=pnl_pct,
                duration=duration,
            )
        )

    return details


def calculate_sortino(
    equity_curve: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: float = 252.0,
) -> float:
    """Calculate the annualised Sortino ratio from an equity curve.

    Args:
        equity_curve: Series of portfolio equity values over time.
        risk_free_rate: Annualised risk-free rate (default 0).
        periods_per_year: Trading periods per year (252 for daily).

    Returns:
        Sortino ratio, or 0.0 when it cannot be computed.
    """
    if equity_curve is None or len(equity_curve) < 2:
        return 0.0

    returns = equity_curve.pct_change().dropna()
    if returns.empty:
        return 0.0

    target = risk_free_rate / periods_per_year
    excess = returns - target
    mean_excess = float(excess.mean())

    # H9: standard TARGET downside deviation = sqrt(mean(min(excess, 0)^2)) over ALL periods. The old
    # code used the mean-centered std of only the negative returns, which collapses to ~0 for a steady
    # loser (Sortino → ~1e15) and is NaN with a single negative return.
    downside = np.minimum(excess.to_numpy(dtype=np.float64), 0.0)
    downside_dev = float(np.sqrt(np.mean(downside ** 2)))

    if downside_dev <= 1e-12:
        # No meaningful downside risk. H10: a bounded value, not a 999.99 sentinel the optimizer
        # chases into degenerate near-no-trade strategies.
        return 0.0 if mean_excess <= 0 else _SORTINO_CAP

    annualised_return = mean_excess * periods_per_year
    annualised_downside = downside_dev * math.sqrt(periods_per_year)
    return float(np.clip(annualised_return / annualised_downside, -_SORTINO_CAP, _SORTINO_CAP))


def calculate_calmar(
    total_return: float,
    max_drawdown: float,
    years: float,
) -> float:
    """Calculate the Calmar ratio = CAGR / |max drawdown|.

    Args:
        total_return: Total return as a FRACTION (e.g. 0.25 for +25%), matching the runner.
        max_drawdown: Maximum drawdown as a fraction (sign-agnostic; ``abs`` is used).
        years: Duration of the backtest in years.

    Returns:
        Calmar ratio (winsorized), or 0.0 when it cannot be computed.
    """
    if years < _MIN_CALMAR_YEARS or max_drawdown == 0:
        return 0.0

    # M2: CAGR (compound annual growth), not arithmetic total_return / years — which over-states short
    # windows (a 3-month window ×4-extrapolated) and misuses the return.
    base = 1.0 + total_return
    cagr = base ** (1.0 / years) - 1.0 if base > 0 else -1.0
    return float(np.clip(cagr / abs(max_drawdown), -_CALMAR_CAP, _CALMAR_CAP))


# ---------------------------------------------------------------------------- #
# C2 — interval-aware annualization (matches backtesting.py 0.6.5)
# ---------------------------------------------------------------------------- #

def periods_per_year(index) -> float:
    """Annualization factor inferred from a DatetimeIndex's bar spacing, matching backtesting.py
    0.6.5's ``annual_trading_days`` (C2): 52 weekly · 12 monthly · 1 yearly · 365 when weekend bars
    are present (e.g. crypto) · else 252 daily. Defaults to 252 for a non-datetime / too-short index.
    """
    try:
        idx = pd.DatetimeIndex(index)
    except Exception:
        return 252.0
    if len(idx) < 3:
        return 252.0
    # Resolution-independent median bar spacing in days (idx may be datetime64[ns|us|…]).
    deltas = np.diff(idx.values).astype("timedelta64[s]").astype(np.float64)
    if deltas.size == 0:
        return 252.0
    freq_days = float(np.median(deltas)) / 86400.0
    if abs(freq_days - 7.0) < 1.0:
        return 52.0
    if 28.0 <= freq_days <= 31.5:
        return 12.0
    if freq_days >= 360.0:
        return 1.0
    # Daily or sub-daily (hourly resamples to daily, like backtesting.py): 365 if weekend bars are
    # present (e.g. crypto), else 252.
    have_weekends = idx.dayofweek.to_series().between(5, 6).mean() > (2.0 / 7.0) * 0.6
    return 365.0 if have_weekends else 252.0


def _geometric_mean(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return 0.0
    lp = np.log1p(r)
    if not np.isfinite(lp).all():
        return float(np.nan_to_num(r.mean()))
    return float(np.exp(lp.sum() / lp.size) - 1.0)


def annualized_sharpe(returns, ppy: float = 252.0, ddof: int = 1) -> float:
    """Simple (arithmetic) annualized Sharpe of a per-bar return series, risk-free 0. Used where only
    a return series is available (e.g. residual / market Sharpe). C2: caller passes the interval-aware
    ``ppy``."""
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=ddof)
    if not np.isfinite(sd) or sd <= 0:
        return 0.0
    return float(r.mean() / sd * math.sqrt(ppy))


def benchmark_sharpe(close: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Annualized Sharpe of a buy-and-hold of *close*, computed the SAME way backtesting.py 0.6.5
    computes the STRATEGY Sharpe (geometric annualized return / compounded annualized volatility,
    interval-aware, resampled to the native frequency) — so benchmark and strategy Sharpe sit on the
    same scale for the gate comparison (C2 / M5 / M6). Falls back to the arithmetic estimator on a
    non-datetime index."""
    s = pd.Series(close).dropna()
    if len(s) < 3:
        return 0.0
    ann = periods_per_year(s.index)
    if not isinstance(s.index, pd.DatetimeIndex):
        return annualized_sharpe(s.pct_change().dropna().to_numpy(), ann)
    freq = {52.0: "W", 12.0: "ME", 1.0: "YE"}.get(ann, "D")
    day_returns = s.resample(freq).last().dropna().pct_change().dropna()
    if len(day_returns) < 2:
        return 0.0
    g = _geometric_mean(day_returns.to_numpy())
    ann_ret = (1.0 + g) ** ann - 1.0
    var = float(day_returns.var(ddof=1))
    ann_vol_sq = (var + (1.0 + g) ** 2) ** ann - (1.0 + g) ** (2 * ann)
    if ann_vol_sq <= 0:
        return 0.0
    return float((ann_ret - risk_free_rate) / math.sqrt(ann_vol_sq))


def calculate_profit_factor(trades: list[TradeDetail]) -> float:
    """Compute profit factor: gross profits / gross losses.

    Args:
        trades: List of :class:`TradeDetail` objects.

    Returns:
        Profit factor (>1 means profitable), winsorized to ``_PROFIT_FACTOR_CAP``. Returns the cap
        when there are no losing trades but some profit, or 0.0 when there are no trades.
    """
    if not trades:
        return 0.0

    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))

    if gross_loss == 0:
        # H10: bounded cap, not a 999.99 sentinel the optimizer chases into no-loss (near-no-trade)
        # strategies.
        return _PROFIT_FACTOR_CAP if gross_profit > 0 else 0.0

    return min(gross_profit / gross_loss, _PROFIT_FACTOR_CAP)
