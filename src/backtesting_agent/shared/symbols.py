"""Symbol → asset-class / home-currency reference heuristics (kernel).

Coarse, best-effort classification of a ticker symbol into an
:class:`~backtesting_agent.shared.types.AssetClass` and its "home currency" (the one
whose events most directly move its price). A real system would resolve these
from a securities-master table; until then these heuristics are the shared
reference both ``risk_gate`` and ``event_context`` rely on.

Moved here in Modularisation Phase 6 (6.3): they previously lived in
``risk_gate.asset_mapping`` as private helpers, which forced ``event_context`` to
import ``risk_gate`` (a wrong-direction capability→capability edge). As kernel
utilities both capabilities import them from here instead.
"""
from __future__ import annotations

from backtesting_agent.shared.types import AssetClass


def symbol_currency_hint(symbol: str) -> str:
    """Best-effort "home currency" of *symbol* (the currency whose events most
    directly move its price). Falls back to USD for unknown symbols."""
    s = symbol.upper()
    # Crypto pairs
    if s.endswith("-USD") or s.endswith("USD") and any(c.isalpha() for c in s):
        # BTC-USD, ETH-USD, etc.
        return "USD"
    # FX pairs: EURUSD, GBPJPY, USDCHF
    if len(s) == 6 and s.isalpha():
        # Take the *quote* currency — that's the one whose events move the price most directly
        return s[3:]
    # Indices
    if s.startswith("^"):
        if "GSPC" in s or "DJI" in s or "IXIC" in s or "NDX" in s or "RUT" in s:
            return "USD"
        if "STOXX" in s or "GDAXI" in s or "FCHI" in s:
            return "EUR"
        if "FTSE" in s:
            return "GBP"
        if "N225" in s:
            return "JPY"
        return "USD"
    # Tickers with explicit suffixes (Yahoo style: AAPL.DE, BMW.DE, 7203.T)
    if "." in s:
        suffix = s.split(".")[-1]
        if suffix in ("DE", "PA", "AS", "MI", "MC"):  # Frankfurt, Paris, Amsterdam, Milan, Madrid
            return "EUR"
        if suffix in ("L",):
            return "GBP"
        if suffix in ("T", "TO"):  # Tokyo
            return "JPY"
        if suffix in ("HK",):
            return "CNY"
    # Default
    return "USD"


def symbol_asset_class(symbol: str) -> AssetClass:
    """Heuristic asset-class for *symbol* — best-effort. Real systems should
    look this up from a securities-master table; we don't have one yet."""
    s = symbol.upper()
    if s.startswith("^"):
        return AssetClass.INDEX
    if "-USD" in s or s.endswith("USD") and any(c.isalpha() for c in s.replace("USD", "")):
        # BTC-USD, ETH-USD
        if any(c in s for c in ("BTC", "ETH", "SOL", "ADA", "DOT", "AVAX", "MATIC", "LINK", "DOGE", "XRP")):
            return AssetClass.CRYPTO
    if len(s) == 6 and s.isalpha():
        return AssetClass.FOREX
    return AssetClass.STOCK
