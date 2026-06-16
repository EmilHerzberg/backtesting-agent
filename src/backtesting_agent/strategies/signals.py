"""Standardized entry/exit signal types for strategies (ATS-171 / E3-S1-T3).

Strategies can produce a richer signal than just BUY/SELL/HOLD: a *direction*
plus a numeric *strength* (for future position-sizing) and a human-readable
*reason* (for logging / explainability). The :class:`TradeSignal` dataclass
formalises this. :class:`StrategyBase` exposes hooks to:

  * generate a TradeSignal on each bar (``generate_signal``)
  * route a TradeSignal to backtesting.py's buy/sell calls (``route_signal``)
  * keep a rolling history of recent signals for inspection (``signal_history``)

Existing strategies do NOT have to migrate; ``next()`` is unchanged unless a
subclass opts in. Strategies that override ``generate_signal`` can call
``self.route_signal(self.generate_signal())`` from their own ``next()``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class SignalDirection(StrEnum):
    """Trade direction: long / short / flat (no position)."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass(frozen=True)
class TradeSignal:
    """A single entry/exit decision produced by a strategy.

    Attributes:
        direction: LONG / SHORT / FLAT.
        strength: Conviction in [0.0, 1.0] (1.0 = fully scaled). Position-sizing
            consumers can scale order quantity by this value; the default
            ``route_signal`` ignores it (sizes by available cash).
        reason: Short, log-friendly explanation, e.g. ``"SMA(20) crossed above SMA(50)"``.
        indicators_used: Names of the indicators that contributed (e.g.
            ``["SMA(20)", "SMA(50)"]``). Useful for explainability dashboards.
    """

    direction: SignalDirection
    strength: float = 1.0
    reason: str = ""
    indicators_used: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Strength is bounded; clamp instead of raising so a buggy indicator
        # cannot kill a backtest mid-run.
        if self.strength < 0.0:
            object.__setattr__(self, "strength", 0.0)
        elif self.strength > 1.0:
            object.__setattr__(self, "strength", 1.0)

    @classmethod
    def long(cls, strength: float = 1.0, reason: str = "", indicators: Iterable[str] = ()) -> "TradeSignal":
        return cls(SignalDirection.LONG, strength, reason, tuple(indicators))

    @classmethod
    def short(cls, strength: float = 1.0, reason: str = "", indicators: Iterable[str] = ()) -> "TradeSignal":
        return cls(SignalDirection.SHORT, strength, reason, tuple(indicators))

    @classmethod
    def flat(cls, reason: str = "", indicators: Iterable[str] = ()) -> "TradeSignal":
        return cls(SignalDirection.FLAT, 0.0, reason, tuple(indicators))


class SignalHistory:
    """Bounded buffer of recent TradeSignals.

    Kept as a class so the ring-buffer semantics are clear. Backed by a
    :class:`collections.deque` with maxlen.
    """

    def __init__(self, maxlen: int = 100) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be > 0")
        self._buf: deque[TradeSignal] = deque(maxlen=maxlen)

    def append(self, signal: TradeSignal) -> None:
        self._buf.append(signal)

    def latest(self) -> TradeSignal | None:
        return self._buf[-1] if self._buf else None

    def all(self) -> list[TradeSignal]:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)
