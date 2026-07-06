"""Phase 2/3 review fixes — regression tests for the confirmed-finding remediations.

Covers: pending-drops-oos-marker (quality PENDING branch), m21-errored-gate (facade surfaces it),
m32-research-loop-still-end-exclusive (_default_fetch end-inclusive), lockbox-init no-silent-downgrade.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.backend.ai.research.quality import quality_summary


def _report(activity=None, benchmark=None):
    results = []
    if activity is not None:
        results.append({"gate_id": "minimum_activity", "status": "PASS", "details": activity})
    if benchmark is not None:
        results.append({"gate_id": "benchmark_relative", "status": "PASS", "details": benchmark})
    return {"results": results}


def test_pending_surfaces_marker_and_stays_capped_at_moderate():
    # Live /candidates defaults a missing OOS outcome to PENDING; the H5 marker must still appear.
    q = quality_summary(
        _report(activity={"tier": "adequate", "t_stat": 2.4}, benchmark={"excess_return": 0.06}),
        oos="PENDING", mode="robustness",
    )
    assert q["tier"] == "moderate"                       # only oos==PASS earns "strong"
    assert "pending" in q["headline"].lower()            # in-sample/no-hold-out disclosure present


def test_gatekeeper_surfaces_errored_gate_through_facade():
    from src.backend.ai.research.gatekeeper import ResearchGatekeeper
    from src.backend.backtesting.gates.pipeline import Gate, GatePipeline, GateSeverity

    class _Boom(Gate):
        gate_id = "boom"
        cost_rank = 1
        severity = GateSeverity.HARD

        def check(self, ctx):
            raise RuntimeError("boom")

    gk = ResearchGatekeeper()
    gk.pipeline = GatePipeline([_Boom()])
    res = gk.evaluate(metrics={"n_trades": 10}, returns=[0.0] * 10, context={})
    # M21: the errored hard gate is attributed via the new facade key (was dropped → None downstream).
    assert res["errored_gate"] == "boom"
    assert res["passed"] is False


def test_default_fetch_makes_yfinance_end_inclusive(monkeypatch):
    import yfinance

    import src.backend.ai.research.run as runmod

    captured: dict = {}

    class _Ticker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):   # now flows via YahooProvider, which also passes interval=
            captured["end"] = kwargs.get("end")
            idx = pd.date_range(kwargs.get("start"), periods=3, freq="D")
            return pd.DataFrame(
                {"Open": [1, 1, 1], "High": [1, 1, 1], "Low": [1, 1, 1], "Close": [1, 1, 1], "Volume": [1, 1, 1]},
                index=idx,
            )

    monkeypatch.setattr(yfinance, "Ticker", _Ticker)
    df = runmod._default_fetch("AAPL", "2020-01-01", "2020-12-31")
    # M32: yfinance end is EXCLUSIVE → the provider passes end+1 day so 2020-12-31 is included.
    assert captured["end"] == "2021-01-01"
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_in_memory_cache_collapses_redundant_fetches():
    """Provider wiring: prepare() is called many times per run for the same (asset, window); the
    in-memory per-run cache must fetch each distinct window ONCE (speed + fewer provider hits, no DB)."""
    from src.backend.ai.research.run import _SimpleDataAgent

    calls: list = []

    def _fake(sec, s, e):
        calls.append((sec, s, e))
        return pd.DataFrame({c: [1, 1, 1] for c in ["Open", "High", "Low", "Close", "Volume"]},
                            index=pd.date_range(s, periods=3, freq="D"))

    agent = _SimpleDataAgent(fetch_fn=_fake)
    agent.prepare("AAPL", "2020-01-01", "2020-12-31")
    agent.prepare("AAPL", "2020-01-01", "2020-12-31")   # same window → cached
    agent.prepare("MSFT", "2020-01-01", "2020-12-31")   # different asset → fetched
    assert len(calls) == 2                              # AAPL once + MSFT once, not 3


def test_use_price_cache_selects_persistent_backend(monkeypatch):
    """use_price_cache=True routes through the persistent CacheManager (paid/intraday quota); the
    yfinance-daily default (False) stays persistence-free so the server DB doesn't grow."""
    import src.backend.ai.research.run as runmod
    import src.backend.marketdata.cache as cachemod

    built: dict = {}

    class _FakeCM:
        def __init__(self, provider=None):
            built["cm"] = True

        def get_or_fetch(self, *a, **k):
            return pd.DataFrame()

    monkeypatch.setattr(cachemod, "CacheManager", _FakeCM)
    off = runmod._SimpleDataAgent()                           # default: no persistence
    on = runmod._SimpleDataAgent(use_price_cache=True)        # opt-in: persistent
    assert off._fetch is runmod._default_fetch
    assert isinstance(on._fetch, runmod._CachedFetch) and built["cm"] is True


async def test_requested_oos_that_cannot_init_raises_not_silently_in_sample(monkeypatch):
    # A run explicitly requesting OOS must fail loudly if the lockbox can't be built — never degrade
    # to counting in-sample candidates as "validated".
    import src.backend.backtesting.lockbox.service as svc

    def _boom(*a, **k):
        raise RuntimeError("cannot open db")

    monkeypatch.setattr(svc, "OOSLockboxService", _boom)
    from src.backend.ai.research.run import run_research

    with pytest.raises(RuntimeError, match="OOS validation was requested"):
        await run_research(
            goal="x", assets=["AAPL"], max_runs=1, target_candidates=1,
            agent_mode="rule_based", enable_oos=True, oos_db_path="/nonexistent/x.db",
            fetch_fn=lambda *a, **k: pd.DataFrame(),
        )
