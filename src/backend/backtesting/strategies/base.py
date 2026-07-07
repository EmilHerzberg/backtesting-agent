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

        # M14: reject unknown/typo'd parameter names. An unrecognised key would otherwise become an
        # inert class attribute — the strategy runs with DEFAULTS while the pipeline records the run
        # under the requested, untested parameterization. Validate against the template's space.
        try:
            _space = cls.parameter_space()
        except NotImplementedError:
            _space = {}
        if _space:
            _unknown = set(params) - set(_space)
            if _unknown:
                raise InvalidParameterError(
                    f"Unknown parameter(s) for {cls.__name__}: {sorted(_unknown)}. Valid: {sorted(_space)}"
                )

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
            * ``SignalDirection.LONG``  -> if not already long, ``self._gated_buy()``
            * ``SignalDirection.SHORT`` -> if not already short, ``self._gated_sell()``
            * ``SignalDirection.FLAT``  -> close any open position via ``self.position.close()``

        Entries (long and short) go through the event gate; exits are never gated.

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
                self._gated_buy()   # H13: entries go through the event gate (no-op when unconfigured)
        elif signal.direction == SignalDirection.SHORT:
            if position is None or not position.is_short:
                self._gated_sell()   # F3: short entries go through the event gate too (no-op when unconfigured)
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

        Subclasses should enter via ``self._gated_buy()`` (which calls this + maps the size correctly);
        this lower-level method is exposed for strategies that need the raw ``(allow, size, gate)`` tuple.

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

    def _gated_buy(self, size_fraction: float = 1.0, **kwargs: Any) -> "AppliedGate | None":
        """Place a long entry THROUGH the event gate, with correct sizing (M13/H13).

        Every template should enter via this helper rather than calling ``self.buy()`` directly, so:
          * the event gate applies to ALL strategies (H13 — it was honoured only by SMACrossover), and
          * the size mapping lives in one place (M13). backtesting.py treats ``size >= 1`` as a SHARE
            COUNT and ``0 < size < 1`` as a fraction of equity, so a naive ``self.buy(size=1.0)`` buys
            ONE SHARE (~2% exposure) while a REDUCE-gated ``size=0.5`` buys 50% of equity — inverting the
            gate. Here a full-equity intent (>= 1.0) maps to ``self.buy()`` (buy-max) and a gated
            fraction stays a fraction.

        With no gate configured this is bit-for-bit ``self.buy()`` (the gate is a passthrough). Returns
        the ``AppliedGate`` (or ``None``) so callers can inspect why an entry was blocked/reduced.
        """
        allow, size, gate = self._apply_event_gate(True, size_fraction)
        if allow and size > 0:
            if size >= 1.0:
                self.buy(**kwargs)                 # full equity (buy-max) — NOT one share
            else:
                self.buy(size=size, **kwargs)      # REDUCE: a true fraction of equity
        return gate

    def _gated_sell(self, size_fraction: float = 1.0, **kwargs: Any) -> "AppliedGate | None":
        """Place a SHORT entry THROUGH the event gate, with correct sizing (F3 — symmetric to _gated_buy).

        A short is a NEW ENTRY too, so the gate's BLOCK_NEW_ENTRIES / REDUCE_POSITION_SIZE semantics apply
        to it exactly as they do to a long (``_apply_event_gate`` is direction-agnostic). Without this,
        a future short-capable strategy routed through :meth:`route_signal` would silently skip the gate.
        With no gate configured this is bit-for-bit ``self.sell()``. Sizing mirrors :meth:`_gated_buy`:
        a full-equity intent (>= 1.0) maps to ``self.sell()`` (sell-max) and a gated fraction stays one.
        """
        allow, size, gate = self._apply_event_gate(True, size_fraction)
        if allow and size > 0:
            if size >= 1.0:
                self.sell(**kwargs)                # full equity (sell-max) — NOT one share
            else:
                self.sell(size=size, **kwargs)     # REDUCE: a true fraction of equity
        return gate

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
