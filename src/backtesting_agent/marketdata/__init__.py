"""Market-data capability — public facade (Modularisation Phase 4).

Owns market-data retrieval (provider abstraction over 9 sources + frozen-snapshot
determinism, caching, quality checks, windowing, asset universes) and the
market-data persistence models (price cache + per-user data-provider keys).

Consumers should import the public API from this package root rather than reaching
into submodules. Re-exports are *lazy* (PEP 562 ``__getattr__``) so importing the
package is cheap and pulls a submodule only on first access.

Note: the legacy async cache helpers in :mod:`marketdata.yahoo` /
:mod:`marketdata.alphavantage` (both expose a ``fetch_and_cache``) are accessed via
their submodules to avoid a name collision; they are not flattened here.
"""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    # provider abstraction + concrete providers
    "DataProvider": "backtesting_agent.marketdata.provider",
    "DataProviderError": "backtesting_agent.marketdata.provider",
    "FrozenSnapshotProvider": "backtesting_agent.marketdata.provider",
    "YahooProvider": "backtesting_agent.marketdata.provider",
    "AlphaVantageProvider": "backtesting_agent.marketdata.provider",
    "PolygonProvider": "backtesting_agent.marketdata.provider",
    "TwelveDataProvider": "backtesting_agent.marketdata.provider",
    "FinnhubProvider": "backtesting_agent.marketdata.provider",
    "CoinGeckoProvider": "backtesting_agent.marketdata.provider",
    "TiingoProvider": "backtesting_agent.marketdata.provider",
    "AlpacaDataProvider": "backtesting_agent.marketdata.provider",
    "AggregatedDataProvider": "backtesting_agent.marketdata.provider",
    "create_aggregated_provider": "backtesting_agent.marketdata.provider",
    "create_provider": "backtesting_agent.marketdata.provider",
    "OHLCV_COLUMNS": "backtesting_agent.marketdata.provider",
    # caching
    "CacheManager": "backtesting_agent.marketdata.cache",
    # quality
    "DataQualityChecker": "backtesting_agent.marketdata.quality",
    "DataQualityReport": "backtesting_agent.marketdata.quality",
    "fill_gaps": "backtesting_agent.marketdata.quality",
    "remove_outliers": "backtesting_agent.marketdata.quality",
    # windowing
    "LookbackConfig": "backtesting_agent.marketdata.windows",
    "train_test_split": "backtesting_agent.marketdata.windows",
    "rolling_windows": "backtesting_agent.marketdata.windows",
    # asset universes
    "AssetType": "backtesting_agent.marketdata.assets",
    "AssetConfig": "backtesting_agent.marketdata.assets",
    "build_universe": "backtesting_agent.marketdata.assets",
    "get_sp500_symbols": "backtesting_agent.marketdata.assets",
    "get_dax_symbols": "backtesting_agent.marketdata.assets",
    "get_nasdaq100_symbols": "backtesting_agent.marketdata.assets",
    "get_crypto_symbols": "backtesting_agent.marketdata.assets",
    "get_etf_symbols": "backtesting_agent.marketdata.assets",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:  # PEP 562
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)
