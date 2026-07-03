"""Backtesting indicator registry and indicator classes.

Import this package to auto-register every indicator in the singleton
:data:`registry`.  Use the registry to discover, instantiate, and query
parameter spaces for all available backtesting indicators::

    from src.backend.backtesting.indicators import registry

    print(registry.list_all())
    sma = registry.get("SMA", period=20)
"""

from src.backend.backtesting.indicators.base import (
    BacktestIndicator,
    Signal,
    suggest_params,
)
from src.backend.backtesting.indicators.registry import (
    BacktestIndicatorRegistry,
    registry,
)

# Import indicator modules to trigger auto-registration
from src.backend.backtesting.indicators.trend import (  # noqa: F401
    ADXIndicator,
    EMAIndicator,
    IchimokuIndicator,
    MACDIndicator,
    SMAIndicator,
)
from src.backend.backtesting.indicators.momentum import (  # noqa: F401
    CCIIndicator,
    RSIIndicator,
    StochasticIndicator,
    WilliamsRIndicator,
)
from src.backend.backtesting.indicators.volatility import (  # noqa: F401
    ATRIndicator,
    BollingerBandsIndicator,
    KeltnerChannelsIndicator,
)
from src.backend.backtesting.indicators.volume import (  # noqa: F401
    OBVIndicator,
    VolumeProfileIndicator,
    VWAPIndicator,
)

__all__ = [
    # Core
    "BacktestIndicator",
    "BacktestIndicatorRegistry",
    "Signal",
    "registry",
    "suggest_params",
    # Trend
    "SMAIndicator",
    "EMAIndicator",
    "MACDIndicator",
    "ADXIndicator",
    "IchimokuIndicator",
    # Momentum
    "RSIIndicator",
    "StochasticIndicator",
    "CCIIndicator",
    "WilliamsRIndicator",
    # Volatility
    "BollingerBandsIndicator",
    "ATRIndicator",
    "KeltnerChannelsIndicator",
    # Volume
    "OBVIndicator",
    "VWAPIndicator",
    "VolumeProfileIndicator",
]
