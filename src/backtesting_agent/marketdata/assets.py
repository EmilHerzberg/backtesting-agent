"""Asset type definitions and universe helpers for backtesting."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AssetType(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    INDEX = "INDEX"
    CRYPTO = "CRYPTO"


@dataclass(frozen=True)
class AssetConfig:
    """Configuration for a single tradeable asset."""

    symbol: str
    asset_type: AssetType = AssetType.STOCK
    exchange: str | None = None
    name: str | None = None


# ------------------------------------------------------------------ #
# Universe helpers — curated lists of major symbols
# ------------------------------------------------------------------ #

def get_sp500_symbols() -> list[str]:
    """Return a curated subset of S&P 500 symbols (top ~30 by weight)."""
    return [
        "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "GOOG", "BRK-B",
        "LLY", "AVGO", "JPM", "TSLA", "UNH", "V", "XOM", "MA", "PG",
        "JNJ", "COST", "HD", "MRK", "ABBV", "WMT", "BAC", "NFLX",
        "CRM", "AMD", "KO", "PEP", "TMO",
    ]


def get_dax_symbols() -> list[str]:
    """Return DAX 40 constituent symbols (Yahoo Finance tickers)."""
    return [
        "SAP.DE", "SIE.DE", "AIR.DE", "ALV.DE", "DTE.DE", "MBG.DE",
        "MUV2.DE", "BAS.DE", "BMW.DE", "IFX.DE", "ADS.DE", "SHL.DE",
        "DB1.DE", "DPW.DE", "HEN3.DE", "BEI.DE", "VOW3.DE", "MRK.DE",
        "RWE.DE", "FRE.DE", "EOAN.DE", "HEI.DE", "DTG.DE", "CBK.DE",
        "MTX.DE", "SY1.DE", "ENR.DE", "QIA.DE", "PAH3.DE", "ZAL.DE",
    ]


def get_nasdaq100_symbols() -> list[str]:
    """Return a curated subset of NASDAQ-100 symbols (top ~25 by weight)."""
    return [
        "AAPL", "MSFT", "AMZN", "NVDA", "META", "GOOGL", "GOOG", "AVGO",
        "TSLA", "COST", "NFLX", "AMD", "ADBE", "PEP", "CSCO", "INTC",
        "CMCSA", "TMUS", "TXN", "QCOM", "AMGN", "ISRG", "INTU", "HON",
        "AMAT",
    ]


def get_crypto_symbols() -> list[str]:
    """Return major cryptocurrency symbols (Yahoo Finance format)."""
    return [
        "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
        "ADA-USD", "DOGE-USD", "AVAX-USD", "DOT-USD", "MATIC-USD",
    ]


def get_etf_symbols() -> list[str]:
    """Return popular ETF symbols covering major asset classes."""
    return [
        "SPY", "QQQ", "IWM", "DIA", "VTI",   # US equity
        "EFA", "EEM", "VWO",                    # International
        "TLT", "IEF", "SHY", "AGG", "BND",    # Bonds
        "GLD", "SLV", "USO",                    # Commodities
        "VNQ", "XLRE",                           # REITs
        "XLF", "XLK", "XLE", "XLV", "XLI",    # Sectors
    ]


def build_universe(
    symbols: list[str],
    asset_type: AssetType = AssetType.STOCK,
    exchange: str | None = None,
) -> list[AssetConfig]:
    """Create a list of AssetConfig from symbol strings."""
    return [
        AssetConfig(symbol=s, asset_type=asset_type, exchange=exchange)
        for s in symbols
    ]
