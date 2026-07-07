"""Combinatorial strategy generator using Optuna for dynamic indicator selection.

STATUS — EXPERIMENTAL / NOT WIRED INTO THE SHIPPING PATH (PATH-1). ``generate_strategy`` has NO
production caller: the CLI ``run_pipeline`` resolves strategies solely from the hand-written
``_STRATEGY_MAP`` (by name), and the AI-research path uses its own template registry — neither invokes
this generator. It is currently reachable only from tests. The M17 fixed-categorical fix below is
therefore correct-but-latent. To ship it, wire ``run_pipeline`` to branch here behind a config flag that
is actually consumed (the former inert ``StrategyConfig.use_generator`` toggle was removed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import optuna
import pandas as pd
from backtesting import Strategy

from src.backend.backtesting.indicators import registry, suggest_params
from src.backend.backtesting.indicators.base import Signal
from src.backend.backtesting.strategies.base import StrategyBase


@dataclass
class SearchSpaceConfig:
    """Constrains the indicator-combinatorial search space (ATS-181).

    Attributes:
        min_indicators: Minimum number of indicators per generated strategy.
        max_indicators: Maximum number of indicators per generated strategy.
        conflicting_groups: Each inner list is a set of indicators that are
            mutually exclusive — only one of them may appear in any single
            generated strategy. Names match the registry keys (case-insensitive).
            Example: ``[["SMA", "EMA"], ["RSI", "STOCH"]]``.
    """

    min_indicators: int = 1
    max_indicators: int = 5
    conflicting_groups: list[list[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.min_indicators < 1:
            raise ValueError("min_indicators must be >= 1")
        if self.max_indicators < self.min_indicators:
            raise ValueError("max_indicators must be >= min_indicators")

    def is_compatible(self, chosen: list[str], candidate: str) -> bool:
        """Return True iff *candidate* can be added to *chosen* without
        violating any conflicting-group rule."""
        cand_norm = candidate.upper()
        chosen_norm = {c.upper() for c in chosen}
        for group in self.conflicting_groups:
            group_norm = {g.upper() for g in group}
            if cand_norm in group_norm and chosen_norm & group_norm:
                return False
        return True


def generate_strategy(
    trial: Any,
    max_indicators: int = 3,
    config: SearchSpaceConfig | None = None,
) -> type[Strategy]:
    """Use an Optuna trial to generate a strategy with dynamic indicator selection.

    The trial selects:
    1. How many indicators to use (1 to *max_indicators*).
    2. Which indicators to use (categorical choice from registry).
    3. Parameters for each chosen indicator.
    4. A weight for each indicator's signal in the voting ensemble.

    Signals are combined via weighted voting:
    - Each indicator produces BUY / SELL / HOLD signals.
    - BUY contributes ``+weight``, SELL contributes ``-weight``, HOLD 0.
    - The final score is compared to a buy/sell threshold (also tuned).

    Args:
        trial: An ``optuna.trial.Trial`` object.
        max_indicators: Maximum number of indicators per strategy.

    Returns:
        A dynamically created ``Strategy`` subclass ready for
        ``backtesting.Backtest``.
    """
    available = registry.list_all()
    if not available:
        raise RuntimeError("No indicators registered. Import the indicators package first.")

    # ATS-181: Honor SearchSpaceConfig if supplied; otherwise fall back to the
    # legacy ``max_indicators`` arg to keep callers working.
    if config is None:
        config = SearchSpaceConfig(min_indicators=1, max_indicators=max_indicators)
    high = min(config.max_indicators, len(available))
    low = min(config.min_indicators, high)
    n_indicators = trial.suggest_int("n_indicators", low, high)

    indicator_configs: list[dict[str, Any]] = []
    chosen_names: list[str] = []
    weights: list[float] = []

    for i in range(n_indicators):
        # M17: Optuna requires a FIXED choice set per named categorical param. The old `remaining`
        # (excluding earlier picks / conflict groups) differed between trials, so trial 2 raised
        # "CategoricalDistribution does not support dynamic value space" and the whole multi-indicator
        # composition feature was unusable. Always suggest from the FULL fixed list, then prune duplicates
        # and conflicts AFTER the suggestion — post-hoc acceptance doesn't change the search space.
        name = trial.suggest_categorical(f"indicator_{i}", available)
        if name in chosen_names or not config.is_compatible(chosen_names, name):
            continue
        chosen_names.append(name)

        # Suggest parameters for this indicator
        space = registry.get_parameter_space(name)
        prefixed_space = {
            f"ind_{i}_{k}": v for k, v in space.items()
        }
        prefixed_params = suggest_params(trial, prefixed_space)
        # Remove the prefix for instantiation
        params = {k.replace(f"ind_{i}_", "", 1): v for k, v in prefixed_params.items()}

        indicator_configs.append({"name": name, "params": params})
        weights.append(trial.suggest_float(f"weight_{i}", 0.1, 1.0))

    # M17-EDGE: the post-hoc dedup/conflict `continue` above can leave FEWER than min_indicators (a trial
    # that drew n_indicators=2 but picked the same or a conflicting indicator at both slots). Prune such a
    # trial rather than silently returning an under-sized strategy that violates the min_indicators
    # contract. (Latent with the default config=None → min_indicators=1, where slot 0 already guarantees
    # one; matters only when a caller supplies min_indicators>1.)
    if len(chosen_names) < config.min_indicators:
        raise optuna.TrialPruned(
            f"only {len(chosen_names)} compatible indicators after dedup (< min {config.min_indicators})"
        )

    buy_threshold = trial.suggest_float("buy_threshold", 0.1, 0.8)
    sell_threshold = trial.suggest_float("sell_threshold", -0.8, -0.1)

    # Freeze into class attributes so backtesting.py can use them
    frozen_configs = list(indicator_configs)
    frozen_weights = list(weights)
    frozen_buy_threshold = buy_threshold
    frozen_sell_threshold = sell_threshold

    class DynamicStrategy(StrategyBase):
        """Dynamically generated multi-indicator voting strategy."""

        _indicator_configs = frozen_configs
        _weights = frozen_weights
        _buy_threshold = frozen_buy_threshold
        _sell_threshold = frozen_sell_threshold

        @classmethod
        def parameter_space(cls) -> dict[str, dict[str, Any]]:
            # The parameter space is defined by the Optuna trial itself
            return {
                "n_indicators": {"type": "int", "low": 1, "high": max_indicators},
                "buy_threshold": {"type": "float", "low": 0.1, "high": 0.8},
                "sell_threshold": {"type": "float", "low": -0.8, "high": -0.1},
            }

        def init(self) -> None:
            self._signals: list[Any] = []
            self._signal_weights: list[float] = []

            for idx, config in enumerate(self._indicator_configs):
                indicator = registry.get(config["name"], **config["params"])

                # Wrap the indicator's signal computation for self.I()
                def _make_signal_fn(ind: Any) -> Any:
                    def _signal_fn(
                        open_: np.ndarray,
                        high: np.ndarray,
                        low: np.ndarray,
                        close: np.ndarray,
                        volume: np.ndarray,
                    ) -> np.ndarray:
                        df = pd.DataFrame({
                            "Open": open_,
                            "High": high,
                            "Low": low,
                            "Close": close,
                            "Volume": volume,
                        })
                        sig = ind.signal(df)
                        # Convert to numeric: BUY=+1, SELL=-1, HOLD=0
                        arr = np.zeros(len(sig), dtype=float)
                        arr[(sig == Signal.BUY).to_numpy()] = 1.0
                        arr[(sig == Signal.SELL).to_numpy()] = -1.0
                        # H12: warm-up bars (indicator not yet converged) → NaN, not a spurious neutral
                        # 0.0, so backtesting.py's leading-NaN skip keeps the strategy from trading
                        # before every indicator has warmed up.
                        arr[ind.compute(df).isna().to_numpy()] = np.nan
                        return arr
                    return _signal_fn

                sig = self.I(
                    _make_signal_fn(indicator),
                    self.data.Open,
                    self.data.High,
                    self.data.Low,
                    self.data.Close,
                    self.data.Volume,
                    name=f"Signal_{config['name']}",
                )
                self._signals.append(sig)
                # P1-04/H12: register each indicator as a strategy attribute so backtesting.py's
                # warm-up detection (_strategy_indicators reads self.__dict__) finds it and skips the
                # leading NaN region — otherwise a DynamicStrategy (indicators kept only in a list)
                # trades on unconverged indicators despite the _signal_fn NaN mask.
                setattr(self, f"_signal_ind_{idx}", sig)
                self._signal_weights.append(self._weights[idx])

        def next(self) -> None:
            # Weighted vote across all indicator signals
            total_weight = sum(self._signal_weights)
            if total_weight == 0:
                return

            score = 0.0
            for sig, w in zip(self._signals, self._signal_weights):
                score += sig[-1] * w

            # Normalise to [-1, 1]
            normalised = score / total_weight

            if normalised >= self._buy_threshold:
                if not self.position:
                    self._gated_buy()   # H13: through the event gate (no-op when unconfigured)
            elif normalised <= self._sell_threshold:
                if self.position:
                    self.position.close()

    # Give the class a unique name for backtesting.py display
    DynamicStrategy.__name__ = f"DynStrat_{trial.number}"
    DynamicStrategy.__qualname__ = DynamicStrategy.__name__

    return DynamicStrategy
