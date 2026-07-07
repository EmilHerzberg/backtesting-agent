"""SMA Crossover strategy for backtesting.py."""

from __future__ import annotations

from typing import Any

import pandas as pd
from backtesting.lib import crossover

from src.backend.backtesting.strategies.base import StrategyBase


class SMACrossover(StrategyBase):
    """Simple Moving Average crossover strategy.

    Buys when the fast SMA crosses above the slow SMA and closes the
    position when the slow SMA crosses above the fast SMA.

    Class-level attributes serve as default parameters and can be
    overridden via :meth:`create_with_params`.
    """

    fast_period: int = 10
    slow_period: int = 50

    @classmethod
    def parameter_space(cls) -> dict[str, dict[str, Any]]:
        return {
            "fast_period": {"type": "int", "low": 5, "high": 50},
            "slow_period": {"type": "int", "low": 20, "high": 200},
        }

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> None:
        """F-016 fix: enforce fast_period + 5 <= slow_period."""
        from src.backend.backtesting.engine.exceptions import InvalidParameterError
        fast = params.get("fast_period", cls.fast_period)
        slow = params.get("slow_period", cls.slow_period)
        if fast + 5 > slow:
            raise InvalidParameterError(
                f"SMACrossover requires fast_period + 5 <= slow_period "
                f"(got fast={fast}, slow={slow})"
            )

    def init(self) -> None:
        close = self.data.Close
        self.fast_sma = self.I(
            lambda x: pd.Series(x).rolling(self.fast_period).mean().values,
            close,
            name=f"SMA({self.fast_period})",
        )
        self.slow_sma = self.I(
            lambda x: pd.Series(x).rolling(self.slow_period).mean().values,
            close,
            name=f"SMA({self.slow_period})",
        )

    def next(self) -> None:
        if crossover(self.fast_sma, self.slow_sma):
            if not self.position:
                # ATS-2080 / M13 / H13 — entry through the event gate with correct sizing. A no-op when
                # no gate config is attached, so the pre-2080 behaviour is preserved bit-for-bit.
                self._gated_buy()
        elif crossover(self.slow_sma, self.fast_sma):
            if self.position:
                self.position.close()
