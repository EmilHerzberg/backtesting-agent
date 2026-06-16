from __future__ import annotations

import math
from abc import ABC, abstractmethod


class ISizer(ABC):
    """Abstract base class for position sizing strategies."""

    @abstractmethod
    def calculate_size(
        self,
        equity: float,
        price: float,
        signal_strength: float = 1.0,
    ) -> float:
        """Calculate the number of shares/units to trade.

        Args:
            equity: Current account equity.
            price: Current asset price.
            signal_strength: Confidence multiplier in ``[0, 1]``.

        Returns:
            Number of shares/units (always >= 0).
        """


class FixedSizer(ISizer):
    """Allocate a fixed dollar amount per trade.

    Args:
        amount: Dollar amount to invest per trade.
    """

    def __init__(self, amount: float = 1000.0) -> None:
        self.amount = amount

    def calculate_size(
        self,
        equity: float,
        price: float,
        signal_strength: float = 1.0,
    ) -> float:
        if price <= 0:
            return 0.0
        raw = (self.amount * signal_strength) / price
        return math.floor(raw)


class PercentSizer(ISizer):
    """Allocate a percentage of equity per trade.

    Args:
        percent: Fraction of equity to allocate (e.g. 0.1 = 10%).
        max_position_pct: Hard cap on any single position as a fraction
            of equity.
    """

    def __init__(
        self,
        percent: float = 0.1,
        max_position_pct: float = 0.25,
    ) -> None:
        self.percent = percent
        self.max_position_pct = max_position_pct

    def calculate_size(
        self,
        equity: float,
        price: float,
        signal_strength: float = 1.0,
    ) -> float:
        if price <= 0 or equity <= 0:
            return 0.0
        alloc_pct = min(self.percent * signal_strength, self.max_position_pct)
        raw = (equity * alloc_pct) / price
        return math.floor(raw)


class KellySizer(ISizer):
    """Position sizing based on the Kelly criterion.

    Uses a fractional Kelly (half-Kelly by default) for safety.

    Args:
        win_rate: Historical win rate in ``[0, 1]``.
        avg_win: Average winning trade return (positive).
        avg_loss: Average losing trade return (positive, i.e. absolute value).
        fraction: Kelly fraction to use (0.5 = half-Kelly).
        max_position_pct: Hard cap on any single position as a fraction
            of equity.
    """

    def __init__(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        fraction: float = 0.5,
        max_position_pct: float = 0.25,
    ) -> None:
        self.win_rate = win_rate
        self.avg_win = avg_win
        self.avg_loss = avg_loss
        self.fraction = fraction
        self.max_position_pct = max_position_pct

    @property
    def kelly_pct(self) -> float:
        """Compute the raw Kelly percentage.

        Formula: ``f* = (p * b - q) / b``
        where ``p`` = win rate, ``q`` = 1 - p, ``b`` = avg_win / avg_loss.

        Returns:
            Kelly fraction (can be negative if edge is negative).
        """
        if self.avg_loss <= 0:
            return 0.0
        b = self.avg_win / self.avg_loss
        if b <= 0:
            return 0.0
        q = 1.0 - self.win_rate
        return (self.win_rate * b - q) / b

    def calculate_size(
        self,
        equity: float,
        price: float,
        signal_strength: float = 1.0,
    ) -> float:
        if price <= 0 or equity <= 0:
            return 0.0
        kelly = self.kelly_pct * self.fraction * signal_strength
        # Never go negative or exceed the hard cap
        alloc_pct = max(0.0, min(kelly, self.max_position_pct))
        raw = (equity * alloc_pct) / price
        return math.floor(raw)


def create_sizer(method: str = "percent", **kwargs: float) -> ISizer:
    """Factory function for position sizers.

    Args:
        method: One of ``"fixed"``, ``"percent"``, ``"kelly"``.
        **kwargs: Keyword arguments forwarded to the chosen sizer class.

    Returns:
        An ``ISizer`` instance.

    Raises:
        ValueError: If *method* is not recognised.
    """
    sizers: dict[str, type[ISizer]] = {
        "fixed": FixedSizer,
        "percent": PercentSizer,
        "kelly": KellySizer,
    }
    cls = sizers.get(method)
    if cls is None:
        raise ValueError(
            f"Unknown sizing method {method!r}. Choose from {list(sizers)}"
        )
    return cls(**kwargs)  # type: ignore[arg-type]
