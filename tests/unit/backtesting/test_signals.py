"""Tests for the TradeSignal interface (ATS-171 / E3-S1-T3)."""

from __future__ import annotations

import pytest

from src.backend.backtesting.strategies.signals import (
    SignalDirection,
    SignalHistory,
    TradeSignal,
)


class TestTradeSignal:
    def test_constructs_long(self):
        s = TradeSignal.long(strength=0.7, reason="rsi oversold", indicators=["RSI(14)"])
        assert s.direction == SignalDirection.LONG
        assert s.strength == 0.7
        assert s.reason == "rsi oversold"
        assert s.indicators_used == ("RSI(14)",)

    def test_constructs_short(self):
        s = TradeSignal.short()
        assert s.direction == SignalDirection.SHORT
        assert s.strength == 1.0

    def test_flat_has_zero_strength(self):
        s = TradeSignal.flat(reason="exit")
        assert s.direction == SignalDirection.FLAT
        assert s.strength == 0.0

    def test_strength_is_clamped_high(self):
        s = TradeSignal(SignalDirection.LONG, strength=1.5)
        assert s.strength == 1.0

    def test_strength_is_clamped_low(self):
        s = TradeSignal(SignalDirection.LONG, strength=-0.5)
        assert s.strength == 0.0

    def test_immutable(self):
        s = TradeSignal.long()
        with pytest.raises(Exception):
            s.strength = 0.5  # type: ignore[misc]

    def test_indicators_stored_as_tuple(self):
        # tuple makes it hashable / safe-to-share
        s = TradeSignal.long(indicators=["A", "B"])
        assert isinstance(s.indicators_used, tuple)


class TestSignalHistory:
    def test_appends_and_reads_latest(self):
        h = SignalHistory(maxlen=5)
        s1 = TradeSignal.long(reason="first")
        s2 = TradeSignal.short(reason="second")
        h.append(s1)
        h.append(s2)
        assert h.latest() is s2
        assert len(h) == 2

    def test_drops_oldest_at_capacity(self):
        h = SignalHistory(maxlen=2)
        h.append(TradeSignal.long(reason="a"))
        h.append(TradeSignal.long(reason="b"))
        h.append(TradeSignal.long(reason="c"))
        all_signals = h.all()
        assert len(all_signals) == 2
        assert all_signals[0].reason == "b"
        assert all_signals[-1].reason == "c"

    def test_latest_on_empty_returns_none(self):
        h = SignalHistory(maxlen=10)
        assert h.latest() is None

    def test_rejects_zero_or_negative_maxlen(self):
        with pytest.raises(ValueError):
            SignalHistory(maxlen=0)
        with pytest.raises(ValueError):
            SignalHistory(maxlen=-1)


class _FakePosition:
    def __init__(self, is_long: bool = False, is_short: bool = False) -> None:
        self.is_long = is_long
        self.is_short = is_short
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.is_long = False
        self.is_short = False


def _make_stub():
    """Return a StrategyBase subclass instance with stubbed buy/sell/position.

    backtesting.Strategy.__init__ requires a broker and data series we don't
    have here; we bypass it via ``object.__new__`` and set only the attrs the
    routing logic touches.

    The parent class declares ``position`` as a read-only property, so we
    override it as a writable instance attr at the subclass level.
    """
    from src.backend.backtesting.strategies.base import StrategyBase

    class _Stub(StrategyBase):
        # Override the read-only position property with a plain instance attr
        position = None  # type: ignore[assignment]

        def init(self):  # noqa: D401 — abstract on parent
            pass

        def next(self):  # noqa: D401 — abstract on parent
            pass

        def buy(self, *args, **kwargs):  # type: ignore[override]
            self._bought += 1
            self.position = _FakePosition(is_long=True)

        def sell(self, *args, **kwargs):  # type: ignore[override]
            self._sold += 1
            self.position = _FakePosition(is_short=True)

    s = object.__new__(_Stub)
    s._bought = 0  # type: ignore[attr-defined]
    s._sold = 0  # type: ignore[attr-defined]
    s.position = _FakePosition()
    return s


class TestRouteSignal:
    def test_long_signal_calls_buy_and_records(self):
        s = _make_stub()
        s.route_signal(TradeSignal.long(reason="cross"))
        assert s._bought == 1
        assert s.signal_history.latest().reason == "cross"

    def test_short_signal_calls_sell(self):
        s = _make_stub()
        s.route_signal(TradeSignal.short(reason="rsi overbought"))
        assert s._sold == 1

    def test_flat_signal_closes_position(self):
        s = _make_stub()
        s.position = _FakePosition(is_long=True)
        pos_ref = s.position
        s.route_signal(TradeSignal.flat(reason="exit"))
        assert pos_ref.closed is True
        assert s._bought == 0
        assert s._sold == 0

    def test_long_when_already_long_does_not_double_buy(self):
        s = _make_stub()
        s.position = _FakePosition(is_long=True)
        s.route_signal(TradeSignal.long())
        assert s._bought == 0

    def test_none_signal_is_noop(self):
        s = _make_stub()
        s.route_signal(None)
        assert s._bought == 0
        assert s._sold == 0
        assert len(s.signal_history) == 0

    def test_default_generate_signal_returns_none(self):
        s = _make_stub()
        assert s.generate_signal() is None
