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
    "DataProvider": "src.backend.marketdata.provider",
    "DataProviderError": "src.backend.marketdata.provider",
    "FrozenSnapshotProvider": "src.backend.marketdata.provider",
    "YahooProvider": "src.backend.marketdata.provider",
    "AlphaVantageProvider": "src.backend.marketdata.provider",
    "PolygonProvider": "src.backend.marketdata.provider",
    "TwelveDataProvider": "src.backend.marketdata.provider",
    "FinnhubProvider": "src.backend.marketdata.provider",
    "CoinGeckoProvider": "src.backend.marketdata.provider",
    "TiingoProvider": "src.backend.marketdata.provider",
    "AlpacaDataProvider": "src.backend.marketdata.provider",
    "AggregatedDataProvider": "src.backend.marketdata.provider",
    "create_aggregated_provider": "src.backend.marketdata.provider",
    "create_aggregated_provider_for_user": "src.backend.marketdata.provider",
    "create_provider": "src.backend.marketdata.provider",
    "OHLCV_COLUMNS": "src.backend.marketdata.provider",
    # caching
    "CacheManager": "src.backend.marketdata.cache",
    # quality
    "DataQualityChecker": "src.backend.marketdata.quality",
    "DataQualityReport": "src.backend.marketdata.quality",
    "fill_gaps": "src.backend.marketdata.quality",
    "remove_outliers": "src.backend.marketdata.quality",
    # windowing
    "LookbackConfig": "src.backend.marketdata.windows",
    "train_test_split": "src.backend.marketdata.windows",
    "rolling_windows": "src.backend.marketdata.windows",
    # asset universes
    "AssetType": "src.backend.marketdata.assets",
    "AssetConfig": "src.backend.marketdata.assets",
    "build_universe": "src.backend.marketdata.assets",
    "get_sp500_symbols": "src.backend.marketdata.assets",
    "get_dax_symbols": "src.backend.marketdata.assets",
    "get_nasdaq100_symbols": "src.backend.marketdata.assets",
    "get_crypto_symbols": "src.backend.marketdata.assets",
    "get_etf_symbols": "src.backend.marketdata.assets",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:  # PEP 562
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)
