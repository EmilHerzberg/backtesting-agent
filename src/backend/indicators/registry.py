from __future__ import annotations

from src.backend.indicators.ema import EMA
from src.backend.indicators.interface import IIndicator
from src.backend.indicators.macd import MACD
from src.backend.indicators.rsi import RSI
from src.backend.indicators.sma import SMA

_REGISTRY: dict[str, type[IIndicator]] = {
    "SMA": SMA,
    "EMA": EMA,
    "RSI": RSI,
    "MACD": MACD,
}


def get_indicator(name: str, **kwargs) -> IIndicator:
    """Create an indicator by name.

    Args:
        name: Indicator name (SMA, EMA, RSI, MACD).
        **kwargs: Indicator-specific parameters (e.g. period=20).

    Raises:
        ValueError: If indicator name is unknown.
    """
    cls = _REGISTRY.get(name.upper())
    if cls is None:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(f"Unknown indicator '{name}'. Available: {available}")
    return cls(**kwargs)


def available_indicators() -> list[str]:
    """Return list of registered indicator names."""
    return sorted(_REGISTRY.keys())
