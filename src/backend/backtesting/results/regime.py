"""Market regime classification and per-regime performance breakdown."""

from __future__ import annotations

import logging
from enum import Enum

import numpy as np
import pandas as pd

from src.backend.backtesting.results.models import BTTrial
from src.backend.backtesting.results.store import ResultStore

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Simplified market regime based on trend direction and volatility level."""

    BULL_LOW_VOL = "bull_low_vol"
    BULL_HIGH_VOL = "bull_high_vol"
    BEAR_LOW_VOL = "bear_low_vol"
    BEAR_HIGH_VOL = "bear_high_vol"
    SIDEWAYS = "sideways"


class VolatilityBucket(Enum):
    """ATS-224 / E5-S4-T3 — Pure-volatility regime buckets.

    Quantile-based 4-bucket classification independent of price trend. Used
    when you want to attribute strategy performance purely to volatility
    regime (vs. the combined SMA+ATR :class:`MarketRegime`).
    """

    LOW = "low_vol"
    NORMAL = "normal_vol"
    HIGH = "high_vol"
    EXTREME = "extreme_vol"


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range over *period* bars.

    Used as the volatility proxy when no VIX series is supplied.
    """
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def classify_by_volatility(
    df: pd.DataFrame,
    *,
    vix_data: pd.Series | None = None,
    atr_period: int = 14,
    quantiles: tuple[float, float, float] = (0.25, 0.75, 0.90),
) -> pd.Series:
    """Bucket each bar into a :class:`VolatilityBucket`.

    Uses *vix_data* when supplied (VIX has its own scale and is the
    canonical macro-volatility proxy); otherwise falls back to ATR
    computed from *df*. Bucket thresholds are quantiles of the chosen
    series — defaults are 25th / 75th / 90th percentile.

    Args:
        df: OHLCV DataFrame with at least Close/High/Low and a sortable
            index (used as the index of the returned series).
        vix_data: Optional pre-aligned VIX series. If passed, must share
            the index of *df*; missing values are forward-filled.
        atr_period: ATR window length, only used when *vix_data* is None.
        quantiles: Three thresholds (low, high, extreme) in (0, 1).

    Returns:
        ``pd.Series`` of :class:`VolatilityBucket` aligned to ``df.index``.
    """
    if not (0.0 < quantiles[0] < quantiles[1] < quantiles[2] < 1.0):
        raise ValueError(
            "quantiles must be a strictly-increasing tuple in (0, 1)"
        )

    if vix_data is not None:
        # Align VIX to df index; forward-fill stale VIX prints.
        vol = vix_data.reindex(df.index).ffill()
    else:
        vol = compute_atr(df, period=atr_period)

    q_low, q_high, q_extreme = vol.quantile(list(quantiles))

    def _bucket(v: float) -> VolatilityBucket:
        if pd.isna(v):
            return VolatilityBucket.NORMAL
        # Inclusive lower-edges so that clustered distributions (many bars
        # tied near a quantile) still distribute across buckets. Upper edge
        # for HIGH is strict so the highest cluster lands in EXTREME.
        if v <= q_low:
            return VolatilityBucket.LOW
        if v <= q_high:
            return VolatilityBucket.NORMAL
        if v < q_extreme:
            return VolatilityBucket.HIGH
        return VolatilityBucket.EXTREME

    return pd.Series([_bucket(v) for v in vol], index=df.index, name="volatility_bucket")


class RegimeAnalyzer:
    """Classify market regimes and break down backtest performance by regime.

    Regime classification uses two signals:

    * **Trend**: slope of the simple moving average over *lookback* bars.
      Positive slope -> bull, negative -> bear, near-zero -> sideways.
    * **Volatility**: Average True Range (ATR) percentile over
      *vol_lookback* bars.  Above median -> high vol, below -> low vol.

    Args:
        lookback: Number of bars for SMA-based trend detection.
        vol_lookback: Number of bars for ATR volatility estimation.
        sideways_threshold: Maximum absolute SMA-slope (normalised) to
            classify a bar as *sideways* rather than bull/bear.
    """

    def __init__(
        self,
        lookback: int = 60,
        vol_lookback: int = 20,
        sideways_threshold: float = 0.0005,
    ) -> None:
        self.lookback = lookback
        self.vol_lookback = vol_lookback
        self.sideways_threshold = sideways_threshold

    # ------------------------------------------------------------------ #
    # Per-bar classification
    # ------------------------------------------------------------------ #

    def classify(self, df: pd.DataFrame) -> pd.Series:
        """Classify each bar into a :class:`MarketRegime`.

        Args:
            df: OHLCV DataFrame with at least *Close*, *High*, *Low*
                columns and a DatetimeIndex.

        Returns:
            A ``pd.Series`` with the same index as *df*, containing
            :class:`MarketRegime` values.  Early bars (insufficient
            lookback) are classified as ``SIDEWAYS``.
        """
        close = df["Close"]
        high = df["High"]
        low = df["Low"]

        # --- Trend: normalised SMA slope -------------------------------- #
        sma = close.rolling(window=self.lookback, min_periods=1).mean()
        sma_slope = sma.diff() / sma.shift(1)
        sma_slope = sma_slope.fillna(0.0)

        # --- Volatility: ATR percentile --------------------------------- #
        tr = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(window=self.vol_lookback, min_periods=1).mean()
        atr_median = atr.expanding(min_periods=1).median()
        high_vol = atr > atr_median

        # --- Combine into regimes --------------------------------------- #
        regimes: list[MarketRegime] = []
        for slope, hv in zip(sma_slope, high_vol):
            if abs(slope) < self.sideways_threshold:
                regimes.append(MarketRegime.SIDEWAYS)
            elif slope > 0:
                regimes.append(
                    MarketRegime.BULL_HIGH_VOL if hv else MarketRegime.BULL_LOW_VOL
                )
            else:
                regimes.append(
                    MarketRegime.BEAR_HIGH_VOL if hv else MarketRegime.BEAR_LOW_VOL
                )

        return pd.Series(regimes, index=df.index, name="regime")

    # ------------------------------------------------------------------ #
    # Performance breakdown by regime
    # ------------------------------------------------------------------ #

    def analyze_by_regime(
        self,
        trial_ids: list[int],
        price_data: dict[str, pd.DataFrame],
        store: ResultStore,
    ) -> dict[str, dict[str, float]]:
        """Break down trade-level PnL by market regime.

        For each trial the method:

        1. Looks up the trial's symbol in *price_data*.
        2. Classifies every bar in that price series.
        3. Assigns each trade to the regime that was active at its entry
           time.
        4. Aggregates PnL, win-rate, and trade-count per regime.

        Args:
            trial_ids: Trials to analyse.
            price_data: Mapping of symbol -> OHLCV DataFrame that covers
                the same period as the trials.
            store: :class:`ResultStore` to load trial data from.

        Returns:
            ``{regime_name: {"total_pnl": ..., "avg_pnl": ...,
            "win_rate": ..., "trade_count": ...}}``
        """
        regime_pnl: dict[str, list[float]] = {r.value: [] for r in MarketRegime}

        for tid in trial_ids:
            trial = store.get_trial(tid)
            if trial is None:
                logger.warning("Trial %d not found, skipping.", tid)
                continue
            if not trial.trade_log:
                continue

            symbol = trial.symbol
            if symbol not in price_data:
                logger.warning(
                    "No price data for symbol %s (trial %d), skipping.",
                    symbol,
                    tid,
                )
                continue

            df = price_data[symbol]
            regime_series = self.classify(df)

            for trade in trial.trade_log:
                if trade.entry_time is None:
                    continue
                try:
                    entry_ts = pd.Timestamp(trade.entry_time)
                except Exception:
                    continue

                # Find the closest bar at or before entry
                mask = regime_series.index <= entry_ts
                if not mask.any():
                    regime = MarketRegime.SIDEWAYS
                else:
                    regime = regime_series.loc[mask].iloc[-1]

                regime_pnl[regime.value].append(trade.pnl or 0.0)

        # Aggregate
        result: dict[str, dict[str, float]] = {}
        for regime_name, pnls in regime_pnl.items():
            count = len(pnls)
            total = sum(pnls)
            avg = total / count if count else 0.0
            wins = sum(1 for p in pnls if p > 0)
            wr = (wins / count * 100.0) if count else 0.0
            result[regime_name] = {
                "total_pnl": round(total, 2),
                "avg_pnl": round(avg, 2),
                "win_rate": round(wr, 2),
                "trade_count": count,
            }
        return result

    # ------------------------------------------------------------------ #
    # Text report
    # ------------------------------------------------------------------ #

    @staticmethod
    def regime_report(results: dict[str, dict[str, float]]) -> str:
        """Generate a human-readable text summary of regime performance.

        Args:
            results: Output of :meth:`analyze_by_regime`.

        Returns:
            Multi-line string report.
        """
        lines: list[str] = ["=== Regime Performance Report ===", ""]
        for regime, metrics in results.items():
            tc = int(metrics.get("trade_count", 0))
            if tc == 0:
                lines.append(f"  {regime:20s}  -- no trades --")
                continue
            lines.append(
                f"  {regime:20s}  "
                f"trades={tc:4d}  "
                f"total_pnl={metrics['total_pnl']:+10.2f}  "
                f"avg_pnl={metrics['avg_pnl']:+8.2f}  "
                f"win_rate={metrics['win_rate']:5.1f}%"
            )
        lines.append("")
        return "\n".join(lines)
