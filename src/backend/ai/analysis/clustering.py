"""Rule-based clustering (V3 Teil 3 — Phase 1).

3 strategy families x 5 asset classes. No ML in Phase 1.
"""
from __future__ import annotations

import statistics
from typing import Any, Optional

# ─── Strategy Family Mapping (V3 Teil 3) ────────────────────────────

STRATEGY_FAMILY: dict[str, str] = {
    # Trend-Following
    "SMACrossover": "trend_following",
    "MACDSignalCross": "trend_following",
    # Mean-Reversion
    "RSIMeanReversion": "mean_reversion",
    "BollingerBreakout": "mean_reversion",
    # Multi-Factor
    "MultiIndicator": "multi_factor",
}

FAMILY_LABELS: dict[str, str] = {
    "trend_following": "Trend-Following",
    "mean_reversion": "Mean-Reversion",
    "multi_factor": "Multi-Factor",
}

# ─── Asset Class Mapping (V3 Teil 3) ────────────────────────────────

# F-008 fix: Erweitert auf S&P 500 Top-100 + weitere gaengige Assets
ASSET_CLASS: dict[str, str] = {}

# US Tech + Communication Services (Big Tech + Semiconductors)
for sym in [
    "AAPL", "MSFT", "NVDA", "META", "GOOGL", "GOOG", "AMZN", "TSLA", "NFLX",
    "ADBE", "CRM", "ORCL", "CSCO", "INTC", "AMD", "AVGO", "QCOM", "TXN",
    "IBM", "NOW", "PANW", "INTU", "MU", "AMAT", "LRCX", "ADI", "KLAC",
]:
    ASSET_CLASS[sym] = "us_tech"

# US Financials
for sym in [
    "JPM", "BAC", "V", "MA", "GS", "WFC", "MS", "C", "BLK", "SCHW",
    "AXP", "PYPL", "SPGI", "CME", "ICE", "USB", "PNC", "TFC", "COF",
    # F-008 follow-up: Berkshire Hathaway (top holding company, financial
    # conglomerate) was missing from the S&P Top-50 coverage.
    "BRK-B", "BRK.B", "BRKB",
]:
    ASSET_CLASS[sym] = "us_finance"

# US Consumer (Staples + Discretionary)
for sym in [
    "WMT", "KO", "PG", "HD", "DIS", "JNJ", "UNH", "PEP", "COST", "MCD",
    "NKE", "SBUX", "MDLZ", "TGT", "LOW", "TJX", "ROST", "BKNG", "CMG", "ABT",
    "PM", "MO", "CL", "KMB", "GIS",
]:
    ASSET_CLASS[sym] = "us_consumer"

# US Healthcare & Pharma
for sym in [
    "LLY", "MRK", "ABBV", "PFE", "TMO", "DHR", "BMY", "AMGN", "GILD",
    "CVS", "ELV", "CI", "MDT", "ISRG", "REGN", "VRTX", "ZTS", "SYK",
]:
    ASSET_CLASS[sym] = "us_health"

# US Energy & Utilities
for sym in [
    "XOM", "CVX", "COP", "EOG", "SLB", "PSX", "MPC", "VLO", "OXY",
    "NEE", "DUK", "SO", "AEP", "D", "EXC", "XEL", "SRE",
]:
    ASSET_CLASS[sym] = "us_energy"

# US Industrials
for sym in [
    "UNP", "HON", "UPS", "RTX", "LMT", "BA", "CAT", "GE", "DE",
    "MMM", "LIN", "FDX", "NOC", "EMR", "ETN", "ITW", "PH",
    "ACN",  # Accenture (consulting/industrial services)
]:
    ASSET_CLASS[sym] = "us_industrial"

# Telecom & Media (non-tech)
for sym in ["VZ", "T", "TMUS", "CMCSA", "CHTR", "WBD", "PARA", "FOX"]:
    ASSET_CLASS[sym] = "us_telecom"

# EU Large Caps (DAX-40 + selected other)
for sym in [
    "SAP", "SIE", "ALV", "BMW", "VOW", "VOW3", "DBK", "BAS", "BAYN",
    "DTE", "MUV2", "ADS", "RWE", "EOAN", "FRE", "MBG", "DHL", "LIN.DE",
    # Tickers as typically seen on yfinance .DE suffix
    "SAP.DE", "SIE.DE", "ALV.DE", "BMW.DE", "VOW3.DE", "DBK.DE",
    "BAS.DE", "BAYN.DE", "DTE.DE", "ADS.DE",
    # Swiss / UK additions
    "NESN.SW", "NOVN.SW", "ROG.SW", "UNA.AS", "ASML",
]:
    ASSET_CLASS[sym] = "eu_large"

# Crypto (major + major alts)
for sym in [
    "BTC", "BTC-USD", "ETH", "ETH-USD", "SOL", "SOL-USD", "BNB", "BNB-USD",
    "ADA", "ADA-USD", "DOT", "DOT-USD", "XRP", "XRP-USD", "DOGE", "DOGE-USD",
    "AVAX", "AVAX-USD", "MATIC", "MATIC-USD", "LINK", "LINK-USD",
    "TRX", "TRX-USD", "LTC", "LTC-USD",
]:
    ASSET_CLASS[sym] = "crypto"

# ETFs (broad market)
for sym in [
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "EFA", "EEM", "GLD",
    "SLV", "USO", "TLT", "HYG", "LQD", "VGK", "EWJ",
]:
    ASSET_CLASS[sym] = "etf_broad"

ASSET_CLASS_LABELS: dict[str, str] = {
    "us_tech": "US-Tech",
    "us_finance": "US-Finance",
    "us_consumer": "US-Consumer",
    "us_health": "US-Health",
    "us_energy": "US-Energy",
    "us_industrial": "US-Industrial",
    "us_telecom": "US-Telecom",
    "eu_large": "EU-Large",
    "crypto": "Crypto",
    "etf_broad": "ETF",
    "other": "Andere",
}


def _strategy_family(name: str) -> str:
    return STRATEGY_FAMILY.get(name, "multi_factor")


def _asset_class(symbol: str) -> str:
    upper = (symbol or "").upper().replace("-USD", "").replace("/USD", "")
    return ASSET_CLASS.get(upper, "other")


def cluster_trials(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster a list of trial dicts by (strategy_family, asset_class).

    Each trial dict needs at least: strategy_name, symbol, sharpe_ratio,
    overfitting_score (optional), is_validated (optional), trade_count.
    """
    buckets: dict[tuple[str, str], list[dict]] = {}
    for t in trials:
        family = _strategy_family(t.get("strategy_name", "") or t.get("strategy", ""))
        asset = _asset_class(t.get("symbol", ""))
        buckets.setdefault((family, asset), []).append(t)

    clusters: list[dict[str, Any]] = []
    for (family, asset), members in buckets.items():
        if len(members) < 3:
            continue  # too small per V3
        sharpes = [m.get("sharpe_ratio") or 0.0 for m in members]
        median_s = statistics.median(sharpes)
        best_s = max(sharpes)
        spread_s = max(sharpes) - min(sharpes)
        wf_validated = sum(1 for m in members if m.get("is_validated"))
        instability = None
        if median_s > 0 and spread_s > 2 * median_s:
            instability = "Instabiler Cluster — Ergebnisse stark parameterabhaengig"
        clusters.append(
            {
                "id": f"{family}__{asset}",
                "label": f"{FAMILY_LABELS[family]} / {ASSET_CLASS_LABELS.get(asset, asset)}",
                "strategy_family": family,
                "asset_class": asset,
                "n_trials": len(members),
                "median_sharpe": round(median_s, 3),
                "best_sharpe": round(best_s, 3),
                "spread_sharpe": round(spread_s, 3),
                "wf_validated_count": wf_validated,
                "instability_warning": instability,
                "trial_ids": [m.get("trial_id") for m in members],
            }
        )
    # Sort by median_sharpe desc, instability last
    clusters.sort(key=lambda c: (c["instability_warning"] is not None, -c["median_sharpe"]))
    return clusters
