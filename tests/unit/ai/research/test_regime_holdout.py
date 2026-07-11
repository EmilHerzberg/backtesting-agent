"""Regime P2 — within-regime forward-slice hold-out (REGIME-P2-HOLDOUT-SPEC v2 §8)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from src.backend.ai.research.loop import (
    VALIDATE_T,
    _compute_regime_decay,
    _days,
    _run_regime_holdout,
    _seed_from_hash,
    _sidak_t_star,
    _train_split,
)
from src.backend.backtesting.gates.basic_gates import MinimumActivityGate, per_trade_t
from src.backend.backtesting.gates.pipeline import GateContext


class _FakeData:
    def prepare(self, security_id, window_start, window_end):
        return {"ws": window_start, "we": window_end}


class _FakeExec:
    """Returns fixed metrics; records the window it was asked to run (to assert select-on-train)."""

    def __init__(self, metrics):
        self._m = metrics
        self.windows = []

    def run(self, spec, data, *, warmup_bars=0):
        # M26: executor.run now takes an optional warm-up-bar count for the OOS/hold-out/decay slices.
        self.windows.append((spec["window_start"], spec["window_end"]))
        return self._m


_STRONG = [0.01 + 0.001 * ((i % 3) - 1) for i in range(30)]   # mean~1%, tiny std → t well above 1.65
_FLAT = [0.05 if i % 2 else -0.05 for i in range(30)]          # mean~0 → t~0 (positive-but-not-significant)
_MODERATE = [0.015 if i % 2 else -0.005 for i in range(30)]    # per-trade t ≈ 2.7: passes 1.65, fails 2.8
_LOSING = [-0.01 - 0.001 * ((i % 3) - 1) for i in range(30)]   # mean ≈ -1% → a genuinely NEGATIVE edge


# ── _train_split (P2-R2) ──────────────────────────────────────────────
def test_train_split_short_window_no_split():
    assert _train_split("2020-01-01", "2020-08-01") is None      # 213d span, 0.40*213 < 120
    assert _train_split("2020-01-01", "2020-10-25") is None      # ~298d → still None


def test_train_split_boundary_and_long():
    # span ≈ 300d → hold = 120d floor
    s = _train_split("2020-01-01", "2020-10-27")                 # 300d
    assert s is not None and _days(s, "2020-10-27") == 120
    # long window → hold = 25% of span
    s5 = _train_split("2015-01-01", "2020-01-01")                # 1826d
    assert s5 is not None and _days(s5, "2020-01-01") == int(0.25 * 1826)


# ── _run_regime_holdout (F-3) ─────────────────────────────────────────
def test_holdout_validated():
    ex = _FakeExec({"n_trades": 30, "trade_returns": _STRONG, "sharpe_annual": 1.4})
    r = _run_regime_holdout({}, _FakeData(), ex, "2019-01-01", "2020-06-01")
    assert r["status"] == "regime_validated"
    assert r["holdout_t"] >= VALIDATE_T and r["holdout_trades"] == 30
    assert ex.windows == [("2019-01-01", "2020-06-01")]          # ran on the hold-out slice


def test_holdout_failed_when_edge_collapses():
    # valconf: `regime_failed` now means a real per-trade test with a NEGATIVE / collapsed edge.
    ex = _FakeExec({"n_trades": 30, "trade_returns": _LOSING, "sharpe_annual": -0.5})
    r = _run_regime_holdout({}, _FakeData(), ex, "2019-01-01", "2020-06-01")
    assert r["status"] == "regime_failed" and r["confidence_tier"] == "failed"


def test_holdout_flat_edge_is_unvalidated_not_failed():
    # valconf/D7: a zero / not-significant-but-positive edge is UNKNOWN (unvalidated), not a collapse.
    ex = _FakeExec({"n_trades": 30, "trade_returns": _FLAT, "sharpe_annual": 0.0})
    r = _run_regime_holdout({}, _FakeData(), ex, "2019-01-01", "2020-06-01")
    assert r["status"] == "unvalidated" and r["confidence_tier"] == "weak"


def test_holdout_thin_stays_unvalidated():
    # No train tempo passed → the bar stays the full ceil (20); 10 trades can't certify → unvalidated.
    ex = _FakeExec({"n_trades": 10, "trade_returns": _STRONG[:10], "sharpe_annual": 1.4})
    r = _run_regime_holdout({}, _FakeData(), ex, "2019-01-01", "2020-06-01")
    assert r["status"] == "unvalidated"       # never a fabricated verdict on too few trades
    assert r["confidence_tier"] in ("weak", "inconclusive") and r["holdout_trades"] == 10


def test_slow_strategy_validates_on_the_scaled_bar():
    # M27 CORE: with a low train tempo the bar scales DOWN (to the floor 5), so a slow strategy with ~6
    # hold-out trades gets a REAL verdict instead of being stuck at `unvalidated` by a fixed-20 bar.
    ex = _FakeExec({"n_trades": 6, "trade_returns": _STRONG[:6], "sharpe_annual": 1.4})
    r = _run_regime_holdout({}, _FakeData(), ex, "2019-01-01", "2020-06-01",
                            train_trades=6, train_days=1826)     # 6 trades over ~5y → very slow
    assert r["basis"] == "per_trade" and r["min_req_trades"] <= 6
    assert r["status"] == "regime_validated"                     # a real verdict, not auto-unvalidated


def test_holdout_no_slice():
    ex = _FakeExec({"n_trades": 30, "trade_returns": _STRONG})
    assert _run_regime_holdout({}, _FakeData(), ex, "", "2020-06-01")["status"] == "unvalidated"
    # slice shorter than MIN_HOLD_DAYS
    short = _run_regime_holdout({}, _FakeData(), ex, "2020-05-01", "2020-06-01")
    assert short["status"] == "unvalidated" and ex.windows == []  # never even ran the backtest


# ── H18/D6: hold-out reuse multiplicity — the bar tightens with the peek count ──
@pytest.mark.finding("H18")
def test_sidak_t_star_tightens_with_reuse():
    # k=1 is clamped to the single-test bar; more peeks give a strictly higher bar.
    assert _sidak_t_star(1) == pytest.approx(VALIDATE_T)
    assert _sidak_t_star(5) > _sidak_t_star(1)
    assert _sidak_t_star(20) > _sidak_t_star(5)
    # 20 reuses at family-wise α=0.05 → t* ≈ 2.8 (Šidák), not the naive 1.65.
    assert 2.7 < _sidak_t_star(20) < 2.9
    # Never loosens below the base bar.
    assert _sidak_t_star(1000) >= VALIDATE_T


@pytest.mark.finding("H18")
def test_holdout_verdict_uses_the_corrected_bar():
    # A t ≈ 2.7 edge: VALIDATED at the single-test bar, but FAILED once the bar is corrected for
    # heavy hold-out reuse (t* = 2.8). Same data, same trades — only the multiplicity bar differs.
    ex = _FakeExec({"n_trades": 30, "trade_returns": _MODERATE, "sharpe_annual": 1.0})
    base = _run_regime_holdout({}, _FakeData(), ex, "2019-01-01", "2020-06-01")
    assert base["status"] == "regime_validated"
    assert base["t_star"] == pytest.approx(VALIDATE_T)

    # valconf: not clearing the reuse-corrected bar with a POSITIVE edge is UNVALIDATED (couldn't certify),
    # not a collapse. The H18 mechanism still applies — the tighter bar flips validated → unvalidated.
    strict = _run_regime_holdout({}, _FakeData(), ex, "2019-01-01", "2020-06-01", t_star=2.8)
    assert strict["status"] == "unvalidated" and strict["confidence_tier"] == "weak"
    assert strict["t_star"] == pytest.approx(2.8)
    assert strict["holdout_t"] == base["holdout_t"]   # identical evidence, stricter bar


# ── shared per_trade_t (no drift between selection + validation) ───────
def test_per_trade_t_matches_gate():
    gate = MinimumActivityGate()
    gate.MIN_TRADES = 5
    gate.ACTIVITY_T = 1.0
    ctx = GateContext(
        metrics={"n_trades": 30, "exposure_time": 0.5, "trade_returns": _STRONG},
        trades=[], returns=np.array(_STRONG), equity_curve=[],
        n_trials_global=10, trial_sr_variance=0.01,
    )
    res = gate.check(ctx)
    assert res.details["t_stat"] == round(per_trade_t(_STRONG), 3)


def test_per_trade_t_edge_cases():
    assert per_trade_t([0.01]) == 0.0            # < 2 trades
    assert per_trade_t([0.02, 0.02, 0.02]) == 99.0   # identical positive → clear pass
    assert per_trade_t([-0.02, -0.02]) == 0.0        # identical non-positive → no edge


# ── decay before + after (P2-4) ───────────────────────────────────────
def test_decay_before_and_after():
    ex = _FakeExec({"sharpe_annual": 0.5})
    d = _compute_regime_decay({}, 1.0, _FakeData(), ex, "2015-01-01", "2016-06-01")
    assert d["before"] is not None and d["after"] is not None
    assert d["before"]["retained_fraction"] == 0.5


def test_decay_after_none_when_window_runs_to_now():
    ex = _FakeExec({"sharpe_annual": 0.5})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = _compute_regime_decay({}, 1.0, _FakeData(), ex, "2015-01-01", today)
    assert d["before"] is not None and d["after"] is None      # no post-window data


@pytest.mark.finding("M29")
def test_decay_near_zero_in_regime_no_absurd_ratio():
    # M29: a near-zero in-regime Sharpe must not yield an absurd retained_fraction. in=0.02, oor=0.5 →
    # naive ratio = 25.0 ("2500% retained"). It must be undefined (None), with the signed delta kept.
    ex = _FakeExec({"sharpe_annual": 0.5})
    b = _compute_regime_decay({}, 0.02, _FakeData(), ex, "2015-01-01", "2016-06-01")["before"]
    assert b["retained_fraction"] is None                      # pre-fix: 25.0
    assert b["retained_delta"] == pytest.approx(0.48, abs=1e-3)   # 0.5 - 0.02 (sign/magnitude preserved)


@pytest.mark.finding("M29")
def test_decay_negative_in_regime_preserves_sign_via_delta():
    ex = _FakeExec({"sharpe_annual": -0.3})
    b = _compute_regime_decay({}, -0.5, _FakeData(), ex, "2015-01-01", "2016-06-01")["before"]
    assert b["retained_fraction"] is None                      # base ≤ 0 → no ratio (pre-fix: None too, but…)
    assert b["retained_delta"] == pytest.approx(0.2, abs=1e-3)   # …the delta -0.3-(-0.5) is NEW (pre-fix: KeyError)


@pytest.mark.finding("M30")
async def test_select_on_train_wiring_through_run_research(monkeypatch, frozen_ohlcv):
    # M30: the select-on-train wiring (strategist/critic get the TRAIN slice; the hold-out runs on
    # [train_end, window_end]) is anti-leakage-critical but was untested — it could silently regress to
    # the full window with zero failures. This drives the REAL run.py split + strategist construction and
    # asserts the window routing. (It PASSES on main — its value is as a regression gate: flipping
    # run.py's `window_end=train_we` to the full window makes assertion C fail.)
    import numpy as np

    import src.backend.ai.research.run as runmod
    from src.backend.ai.research.loop import _train_split

    windows: list[tuple] = []

    class _SpyExec:
        def __init__(self, *a, **k):
            pass

        def run(self, spec, data, *, warmup_bars=0):
            windows.append((spec.get("window_start"), spec.get("window_end")))
            return {
                "sharpe_annual": 1.4, "total_return": 0.3, "max_drawdown": -0.1, "n_trades": 30,
                "trade_returns": _STRONG, "exposure_time": 0.5, "win_rate": 0.6, "profit_factor": 1.8,
                "buy_hold_return": 0.1, "buy_hold_sharpe": 0.5, "buy_hold_max_drawdown": -0.15,
                "returns": np.zeros(30), "equity_curve": [100.0] * 30,
                "strategy_hash": spec.get("strategy_hash", ""), "template_id": spec.get("template_id", ""),
                "params": {}, "commission": 0.00145, "ohlcv_df": data, "lagged_sharpe_annual": None,
            }

    class _PassGate:
        def __init__(self, *a, **k):
            pass

        def evaluate(self, *a, **k):
            return {"passed": True,
                    "results": [{"gate_id": "minimum_activity", "status": "PASS",
                                 "details": {"tier": "adequate"}}]}

        def update_registry_stats(self, *a, **k):
            pass

    monkeypatch.setattr(runmod, "ResearchExecutor", _SpyExec)
    monkeypatch.setattr(runmod, "ResearchGatekeeper", _PassGate)

    captured: dict = {}
    await runmod.run_research(
        goal="x", assets=["SPY"], mode="regime", window_start="2015-06-01", window_end="2018-01-01",
        agent_mode="rule_based", enable_oos=False, enable_leakage_canary=False,
        max_runs=1, target_candidates=1, fetch_fn=frozen_ohlcv,
        on_start=lambda s: captured.setdefault("state", s),
    )
    st = captured["state"]                                   # captured before train_end is set → read now
    split = _train_split(st.window_start, st.window_end)
    assert split and st.train_end == split                  # A: the split is recorded on state
    assert st.window_end == "2018-01-01"                    # B: the FULL window is kept for the hold-out bound
    assert (st.window_start, split) in windows              # C: SELECTION ran on the TRAIN slice (not full)
    assert (split, st.window_end) in windows                # D: HOLD-OUT ran on [train_end, window_end]


@pytest.mark.finding("M49")
async def test_regime_failed_candidate_does_not_advance_the_watermark(monkeypatch, frozen_ohlcv):
    # M49 (F1): a regime_failed idea is overfit-by-definition (cleared the soft gates on a HIGH in-sample
    # Sharpe, then its edge collapsed out-of-fit), so it must NOT advance the plateau watermark — else it
    # re-enters the exact pin-the-watermark harm M49 fixes, in regime mode where regime_failed is common.
    import numpy as np

    import src.backend.ai.research.run as runmod

    class _SpyExec:
        def __init__(self, *a, **k):
            pass

        def run(self, spec, data, *, warmup_bars=0):
            # Window-aware: the SELECTION run (train slice) has a HIGH in-sample Sharpe (5.0), but the
            # HOLD-OUT run (window_end == the full window end) COLLAPSES to a negative edge → regime_failed.
            failed = spec.get("window_end") == "2018-01-01"
            return {
                "sharpe_annual": -2.0 if failed else 5.0, "total_return": -0.2 if failed else 0.4,
                "max_drawdown": -0.1, "n_trades": 30, "trade_returns": _LOSING if failed else _STRONG,
                "exposure_time": 0.5, "win_rate": 0.5, "profit_factor": 1.1,
                "buy_hold_return": 0.1, "buy_hold_sharpe": 0.5, "buy_hold_max_drawdown": -0.15,
                "benchmark_available": True, "returns": np.zeros(30), "equity_curve": [100.0] * 30,
                "strategy_hash": spec.get("strategy_hash", ""), "template_id": spec.get("template_id", ""),
                "params": {}, "commission": 0.00145, "ohlcv_df": data, "lagged_sharpe_annual": None,
            }

    class _PassGate:
        def __init__(self, *a, **k):
            pass

        def evaluate(self, *a, **k):
            return {"passed": True, "results": [{"gate_id": "minimum_activity", "status": "PASS",
                                                 "details": {"tier": "adequate"}}]}

        def update_registry_stats(self, *a, **k):
            pass

    monkeypatch.setattr(runmod, "ResearchExecutor", _SpyExec)
    monkeypatch.setattr(runmod, "ResearchGatekeeper", _PassGate)

    captured: dict = {}
    await runmod.run_research(
        goal="x", assets=["SPY"], mode="regime", window_start="2015-06-01", window_end="2018-01-01",
        agent_mode="rule_based", enable_oos=False, enable_leakage_canary=False,
        max_runs=1, target_candidates=1, fetch_fn=frozen_ohlcv,
        on_start=lambda s: captured.setdefault("state", s),
    )
    st = captured["state"]
    assert st.candidates and st.candidates[0].validation_status == "regime_failed"   # precondition (t~0 < t*)
    assert 5.0 not in st.best_sharpe_on_asset                                          # pre-fix: [5.0]


@pytest.mark.finding("M27")
def test_thin_holdout_still_reports_observed_evidence():
    # M27: a too-thin hold-out is UNVALIDATED (not a verdict), but the observed evidence must not be dropped —
    # valconf enriches every result with the tier, the basis, the sample sizes, the t, and the CI.
    ex = _FakeExec({"n_trades": 10, "trade_returns": _STRONG[:10], "sharpe_annual": 1.4})
    r = _run_regime_holdout({}, _FakeData(), ex, "2019-01-01", "2020-06-01")
    assert r["status"] == "unvalidated"
    assert r["holdout_sharpe"] == pytest.approx(1.4)           # observed number never dropped
    for k in ("holdout_t", "confidence_tier", "basis", "observed_sharpe", "n_bars_in_market",
              "min_req_trades", "ci_low", "ci_high", "ci_level"):
        assert k in r, k


@pytest.mark.finding("valconf-ci-seed")
def test_seed_from_hash_is_deterministic_and_decorrelated():
    """valconf CI seeding: the bootstrap seed is a STABLE function of the strategy fingerprint — same hash →
    same seed (the band is reproducible across runs, not tied to a run seed), different hashes → different
    seeds (each strategy's draws are decorrelated). No crash on empty; a valid non-negative RNG seed."""
    assert _seed_from_hash("abc123") == _seed_from_hash("abc123")        # deterministic
    assert _seed_from_hash("abc123") != _seed_from_hash("def456")        # decorrelated across strategies
    assert _seed_from_hash("") == _seed_from_hash("")                     # empty is stable, not a crash
    s = _seed_from_hash("deadbeef")
    assert isinstance(s, int) and 0 <= s <= 0xFFFFFFFF                    # a valid non-negative RNG seed

    # and it genuinely drives the CI: two fingerprints → different bands, each reproducible.
    from src.backend.backtesting.engine.confidence import block_bootstrap_sharpe_ci
    rng = np.random.default_rng(1)
    daily = list(rng.normal(0.001, 0.01, 60))
    ci_a = block_bootstrap_sharpe_ci(daily, 252.0, seed=_seed_from_hash("stratA"))
    ci_b = block_bootstrap_sharpe_ci(daily, 252.0, seed=_seed_from_hash("stratB"))
    assert ci_a != ci_b                                                  # different fingerprints → different draws
    assert ci_a == block_bootstrap_sharpe_ci(daily, 252.0, seed=_seed_from_hash("stratA"))  # reproducible
