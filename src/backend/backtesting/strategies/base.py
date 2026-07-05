"""Base class for backtesting strategies compatible with backtesting.py."""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import TYPE_CHECKING, Any

from backtesting import Strategy

from src.backend.backtesting.engine.exceptions import InvalidParameterError
from src.backend.backtesting.strategies.signals import (
    SignalDirection,
    SignalHistory,
    TradeSignal,
)

if TYPE_CHECKING:  # pragma: no cover -- typing only
    import pandas as pd

    from src.backend.backtesting.config.schema import EventGateConfig
    from src.backend.backtesting.event_gate import AppliedGate


class StrategyBase(Strategy):
    """Base class for all backtesting strategies.

    Extends ``backtesting.Strategy`` with Optuna parameter-space support
    and a factory method for creating parameterised subclasses (required
    because backtesting.py reads parameters from class-level attributes).
    """

    # ATS-1705 — strategy template versioning. Bump when the strategy
    # logic changes in a way that affects backtest results.
    version: int = 1

    @classmethod
    def template_hash(cls) -> str:
        """SHA-256 of source code + version + parameter schema.

        Changes to any of these produce a different hash, ensuring that
        the registry can distinguish between different versions of the
        same strategy template.
        """
        source = inspect.getsource(cls)
        schema = json.dumps(cls.parameter_space(), sort_keys=True, default=str)
        payload = f"{source}\n---version:{cls.version}---\n{schema}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def parameter_space(cls) -> dict[str, dict[str, Any]]:
        """Return Optuna parameter-space definition.

        Each key is a parameter name; the value is a dict compatible with
        :func:`src.backend.backtesting.indicators.base.suggest_params`.

        Example::

            {
                "fast_period": {"type": "int", "low": 5, "high": 50},
                "slow_period": {"type": "int", "low": 20, "high": 200},
            }
        """
        raise NotImplementedError

    @classmethod
    def validate_params(cls, params: dict[str, Any]) -> None:
        """F-016..F-020: Validate parameter combinations.

        Override in subclasses to enforce constraints like ``fast < slow``.
        Default: no constraints.

        Raises:
            InvalidParameterError: if combination is invalid.
        """
        pass

    @classmethod
    def create_with_params(cls, **params: Any) -> type[StrategyBase]:
        """Create a ``Strategy`` subclass with fixed parameters as class attributes.

        backtesting.py requires strategy parameters to be class-level
        attributes.  This factory method dynamically creates a subclass
        with the supplied *params* baked in.

        Args:
            **params: Parameter values to set as class attributes.

        Returns:
            A new ``type`` that is a subclass of the calling class.

        Raises:
            InvalidParameterError: if validate_params rejects the combination.
        """
        # F-016..F-020 fix: validate constraints BEFORE creating subclass
        cls.validate_params(params)

        attrs: dict[str, Any] = {k: v for k, v in params.items()}
        # Preserve access to the original parameter_space definition
        parent = cls

        @classmethod  # type: ignore[misc]
        def _parameter_space(cls_: type) -> dict[str, dict[str, Any]]:
            return parent.parameter_space()

        attrs["parameter_space"] = _parameter_space
        return type(f"{cls.__name__}_{id(params)}", (cls,), attrs)

    # ------------------------------------------------------------------ #
    # ATS-171 / E3-S1-T3 — Standardized TradeSignal interface
    # ------------------------------------------------------------------ #

    SIGNAL_HISTORY_LEN = 100

    def _ensure_signal_history(self) -> SignalHistory:
        """Lazy-init the per-instance signal history.

        backtesting.py constructs strategies with limited control over
        ``__init__``; lazy-initialisation keeps subclasses free of an
        explicit super().__init__() call.
        """
        history = getattr(self, "_signal_history", None)
        if history is None:
            history = SignalHistory(maxlen=self.SIGNAL_HISTORY_LEN)
            self._signal_history = history
        return history

    @property
    def signal_history(self) -> SignalHistory:
        """Rolling buffer of the strategy's recent TradeSignals.

        Subclasses can read from ``signal_history.latest()`` to make
        next-bar decisions conditional on previous signals.
        """
        return self._ensure_signal_history()

    def generate_signal(self) -> TradeSignal | None:
        """Return a :class:`TradeSignal` for the current bar — or ``None``.

        Default: ``None`` (no opinion). Strategies opt in by overriding
        this and calling ``self.route_signal(self.generate_signal())``
        from their own ``next()``. Returning ``None`` is a no-op for
        :meth:`route_signal`.
        """
        return None

    def record_signal(self, signal: TradeSignal) -> None:
        """Append *signal* to the rolling history (no order is placed)."""
        self._ensure_signal_history().append(signal)

    def route_signal(self, signal: TradeSignal | None) -> None:
        """Translate a :class:`TradeSignal` into backtesting.py buy/sell.

        Behavior:
            * ``None``           -> no-op
            * ``SignalDirection.LONG``  -> if not already long, ``self.buy()``
            * ``SignalDirection.SHORT`` -> if not already short, ``self.sell()``
            * ``SignalDirection.FLAT``  -> close any open position via ``self.position.close()``

        The signal is recorded in :attr:`signal_history` regardless. The
        default ignores ``signal.strength`` — wire up custom sizing in a
        subclass if you need fractional positions.
        """
        if signal is None:
            return
        self.record_signal(signal)
        position = getattr(self, "position", None)
        if signal.direction == SignalDirection.LONG:
            if position is None or not position.is_long:
                self.buy()
        elif signal.direction == SignalDirection.SHORT:
            if position is None or not position.is_short:
                self.sell()
        elif signal.direction == SignalDirection.FLAT:
            if position is not None and (position.is_long or position.is_short):
                position.close()

    # ------------------------------------------------------------------ #
    # ATS-2080 — Event-Gate integration
    # ------------------------------------------------------------------ #

    # Default attribute slots so subclasses can rely on them without an
    # ``__init__``. backtesting.py walks class attributes during init —
    # keeping these at the class level (rather than the instance) means
    # they're inherited rather than collided-on.
    _gates_df: "pd.DataFrame | None" = None
    _event_gate_config: "EventGateConfig | None" = None
    _event_gate_symbol: str | None = None
    # C1 — warm-up trade mask. The runner sets this to the first post-warm-up bar's timestamp when a
    # warm-up prefix is configured; entries before it are suppressed so indicators converge on the
    # prefix without any in-sample trades leaking into the evaluation window. None = no masking.
    _trade_start: Any = None

    def _ensure_gate_logs(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Lazy-init per-instance blocked / reduced gate logs.

        backtesting.py constructs strategies without giving us an
        ``__init__`` hook, so we mirror the ``signal_history`` pattern:
        check-and-create on first access. Returned tuple is
        ``(blocked_log, reduced_log)`` — caller appends dicts.
        """
        blocked = getattr(self, "blocked_log", None)
        reduced = getattr(self, "reduced_log", None)
        if blocked is None:
            blocked = []
            self.blocked_log = blocked  # type: ignore[attr-defined]
        if reduced is None:
            reduced = []
            self.reduced_log = reduced  # type: ignore[attr-defined]
        return blocked, reduced

    def _current_bar_date(self) -> Any:
        """Return the current bar's date — falls back to ``None`` on legacy data.

        backtesting.py exposes ``self.data.index`` as a numpy array of
        timestamps. The current bar is the last index; we convert to a
        ``datetime.date`` so the gate-lookup signature stays stable
        across daily / intraday strategies.
        """
        try:
            ts = self.data.index[-1]
        except (AttributeError, IndexError):
            return None
        # ``ts`` is a numpy datetime64 — convert via pandas for tz-safety.
        import pandas as pd

        return pd.Timestamp(ts).date()

    def _apply_event_gate(
        self, allow_entry: bool, size_fraction: float,
    ) -> tuple[bool, float, "AppliedGate | None"]:
        """Apply the event-gate (if configured) to a pending entry signal.

        Subclasses call this immediately before placing an entry order:

            allow, size, gate = self._apply_event_gate(True, 1.0)
            if allow and size > 0:
                self.buy(size=size)

        Behaviour:
            * If no gate config or ``enabled=False``: returns the inputs
              unchanged with ``AppliedGate=None``.
            * If a BLOCK gate is active: returns ``(False, 0.0, gate)``
              and appends to ``self.blocked_log``.
            * If a REDUCE gate is active: returns
              ``(allow_entry, size_fraction * gate.multiplier, gate)``
              and appends to ``self.reduced_log``.
            * No active gate: returns the inputs unchanged with
              ``AppliedGate=None``.

        Args:
            allow_entry: whether the strategy already wants to enter
                this bar. ``False`` short-circuits — we don't log gates
                against trades the strategy wasn't going to take anyway.
            size_fraction: the size scalar the strategy planned to pass
                to ``self.buy``. Typically ``1.0`` for the all-in default.

        Returns:
            ``(allow_entry, size_fraction, gate_or_none)``.
        """
        cfg = self._event_gate_config
        if cfg is None or not getattr(cfg, "enabled", False):
            return allow_entry, size_fraction, None
        if not allow_entry:
            return allow_entry, size_fraction, None
        # Lazy import — keeps this base file importable even when the
        # event-context package fails to import (e.g. minimal CI envs).
        from src.backend.backtesting.event_gate import apply_gate_at_decision

        decision_date = self._current_bar_date()
        if decision_date is None:
            return allow_entry, size_fraction, None

        gate = apply_gate_at_decision(
            self._gates_df,
            decision_date=decision_date,
            asset_symbol=self._event_gate_symbol or "",
            allowed_actions=list(cfg.allowed_actions),
            min_severity=cfg.min_asset_severity,
            min_importance=cfg.min_event_importance,
        )
        if gate is None:
            return allow_entry, size_fraction, None

        blocked, reduced = self._ensure_gate_logs()
        entry = {
            "decision_date": decision_date,
            "event_id": gate.event_id,
            "gate_action": gate.gate_action,
            "multiplier": gate.multiplier,
            "reason": gate.reason,
            "risk_severity": gate.risk_severity,
        }
        if gate.gate_action == "BLOCK_NEW_ENTRIES":
            blocked.append(entry)
            return False, 0.0, gate
        if gate.gate_action == "REDUCE_POSITION_SIZE":
            new_size = size_fraction * gate.multiplier
            reduced.append(entry)
            return allow_entry, new_size, gate
        # Unknown / NO_GATE — passthrough.
        return allow_entry, size_fraction, gate

    # ------------------------------------------------------------------ #
    # C1 — warm-up trade mask (generic across every subclass)
    # ------------------------------------------------------------------ #

    def _in_warmup(self) -> bool:
        """True while the current bar precedes the configured warm-up boundary (C1)."""
        ts = self._trade_start
        if ts is None:
            return False
        try:
            import pandas as pd

            return pd.Timestamp(self.data.index[-1]) < pd.Timestamp(ts)
        except (AttributeError, IndexError, TypeError, ValueError):
            return False

    def buy(self, *args: Any, **kwargs: Any):  # noqa: D401 -- backtesting.py entry API
        """Open a long — suppressed during the warm-up region (C1)."""
        if self._in_warmup():
            return None
        return super().buy(*args, **kwargs)

    def sell(self, *args: Any, **kwargs: Any):  # noqa: D401 -- backtesting.py entry API
        """Open a short — suppressed during the warm-up region (C1)."""
        if self._in_warmup():
            return None
        return super().sell(*args, **kwargs)
