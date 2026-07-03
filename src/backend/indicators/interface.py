from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from enum import StrEnum


class Signal(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class IIndicator(ABC):
    """Abstract base class for all technical indicators."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Indicator name (e.g. 'SMA', 'RSI')."""

    @abstractmethod
    def calculate(self, prices: list[Decimal]) -> Decimal | None:
        """Calculate indicator value from a list of closing prices.

        Args:
            prices: List of closing prices, oldest first.

        Returns:
            The indicator value, or None if not enough data.
        """

    @abstractmethod
    def signal(self, prices: list[Decimal]) -> Signal:
        """Generate a trading signal from closing prices.

        Args:
            prices: List of closing prices, oldest first.

        Returns:
            BUY, SELL, or HOLD signal.
        """

    @property
    @abstractmethod
    def min_periods(self) -> int:
        """Minimum number of price points required for calculation."""
