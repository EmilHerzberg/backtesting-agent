"""Built-in preset configurations for common backtesting scenarios."""

from __future__ import annotations

from backtesting_agent.config.schema import (
    AssetsConfig,
    BacktestFullConfig,
    OptunaConfig,
    StrategyConfig,
    TimeConfig,
    WalkForwardYaml,
)

# 20 diversified large-cap symbols for the "full" preset
_FULL_SYMBOLS: list[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
    "META", "NVDA", "JPM", "V", "JNJ",
    "WMT", "PG", "MA", "UNH", "HD",
    "DIS", "BAC", "XOM", "NFLX", "ADBE",
]


PRESETS: dict[str, BacktestFullConfig] = {
    "quick": BacktestFullConfig(
        assets=AssetsConfig(symbols=["AAPL"]),
        time=TimeConfig(lookback="1y"),
        strategy=StrategyConfig(names=["SMACrossover"]),
        optuna=OptunaConfig(n_trials=50),
    ),
    "standard": BacktestFullConfig(
        assets=AssetsConfig(symbols=["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]),
        time=TimeConfig(lookback="2y"),
        strategy=StrategyConfig(
            names=["SMACrossover", "RSIMeanReversion", "MACDSignalCross"]
        ),
        optuna=OptunaConfig(n_trials=100),
    ),
    "full": BacktestFullConfig(
        assets=AssetsConfig(symbols=_FULL_SYMBOLS),
        time=TimeConfig(lookback="5y"),
        strategy=StrategyConfig(
            names=[
                "SMACrossover",
                "RSIMeanReversion",
                "BollingerBreakout",
                "MACDSignalCross",
                "MultiIndicator",
            ]
        ),
        optuna=OptunaConfig(n_trials=500),
        walk_forward=WalkForwardYaml(enabled=True),
    ),
}


def get_preset(name: str) -> BacktestFullConfig:
    """Return a deep copy of a preset configuration.

    Args:
        name: Preset name -- "quick", "standard", or "full".

    Returns:
        A fresh BacktestFullConfig instance.

    Raises:
        KeyError: If the preset name is unknown.
    """
    if name not in PRESETS:
        available = ", ".join(sorted(PRESETS))
        raise KeyError(
            f"Unknown preset '{name}'. Available presets: {available}"
        )
    # model_copy creates a deep copy so callers can mutate without side effects
    return PRESETS[name].model_copy(deep=True)
