"""Coverage-v2 effective-N wire (RT1/B1/B2/B4/B5) — estimator + campaign size + gate split."""

import numpy as np
import pytest

from src.backend.ai.research.effective_n import (
    campaign_search_size,
    frozen_ratio,
    mp_denoised_effective_count,
    participation_ratio,
)
from src.backend.backtesting.gates.deflated_sharpe import DeflatedSharpeGate
from src.backend.backtesting.gates.pipeline import GateContext, GateStatus


# ── RT1 estimator: PF3-style known-K recovery ─────────────────────────

def _clone_family_corr(k_factors: int, clones_per: int, t_obs: int, noise: float,
                       seed: int = 7) -> np.ndarray:
    """K independent factors, each cloned m times with idiosyncratic noise."""
    rng = np.random.default_rng(seed)
    factors = rng.standard_normal((k_factors, t_obs))
    series = np.vstack([f + noise * rng.standard_normal(t_obs)
                        for f in factors for _ in range(clones_per)])
    return np.corrcoef(series)


@pytest.mark.finding("RT1")
def test_known_k_recovery_on_clone_families():
    # 4 independent factors x 10 near-clones each: the raw count is 40 but the true
    # independent multiplicity is ~4. The estimator must land near K, not near N.
    corr = _clone_family_corr(k_factors=4, clones_per=10, t_obs=3000, noise=0.05)
    meff = mp_denoised_effective_count(corr, 3000)
    assert 3.0 <= meff <= 6.0

    # Fully independent family: Meff must stay near N (no phantom reduction).
    corr_ind = _clone_family_corr(k_factors=12, clones_per=1, t_obs=5000, noise=0.0)
    assert mp_denoised_effective_count(corr_ind, 5000) >= 10.0


@pytest.mark.finding("RT1")
def test_beta_dominated_family_collapses_documented_limitation():
    # Track-4 review (HIGH, recorded limitation): real strategy families share the asset's
    # market mode (off-diag corr floors ~0.55 at any grid distance), and the MP clip folds the
    # bulk into that mode — Meff collapses to ~1-2 REGARDLESS of true strategy diversity. This
    # is WHY the v1 wire uses raw visited counts and why the PF2/PF3 phase must strip the
    # market mode before any measured reduction reaches the gate's N. This test pins the
    # limitation so a future change that silently wires the raw estimator trips it.
    rng = np.random.default_rng(11)
    market = rng.standard_normal(4000)
    series = np.vstack([0.8 * market + 0.2 * rng.standard_normal(4000)
                        for _ in range(30)])
    meff = mp_denoised_effective_count(np.corrcoef(series), 4000)
    assert meff < 3.0     # collapses despite 30 idiosyncratically-distinct streams


@pytest.mark.finding("RT1")
def test_participation_ratio_bounds():
    assert participation_ratio(np.array([1.0, 1.0, 1.0, 1.0])) == pytest.approx(4.0)
    assert participation_ratio(np.array([4.0, 0.0, 0.0, 0.0])) == pytest.approx(1.0)
    # tiny negative eigenvalues (rounding dents) are clipped, not amplified
    assert participation_ratio(np.array([2.0, 1.0, -1e-9])) == pytest.approx(9 / 5, rel=1e-3)


def test_frozen_ratios_load_and_unknown_template_is_no_reduction():
    # The committed calibration artifact: sweep families are near-clones (ratio ≪ 1).
    for t in ("sma_crossover", "rsi_reversion", "bollinger_breakout", "macd_cross"):
        assert 0.0 < frozen_ratio(t) < 0.25
    assert frozen_ratio("never_calibrated_template") == 1.0


# ── B1/B2/B5: the campaign search size ────────────────────────────────

@pytest.mark.finding("B5")
def test_campaign_search_size_is_raw_visited_count_with_run_floor():
    visited = {("sma_crossover", "AAPL"): {"c1", "c2", "c3"},
               ("rsi_reversion", "AAPL"): {"c1"},
               ("rsi_reversion", "MSFT"): set()}
    # raw sum = 4 (B5 conservative upper bound — NO sweep-ratio reduction, module doc)
    assert campaign_search_size(visited, n_run=2) == 4
    # the max(., n_run) floor: enabling can only TIGHTEN vs the per-run status quo
    assert campaign_search_size(visited, n_run=9) == 9
    assert campaign_search_size({}, n_run=7) == 7
    assert campaign_search_size(None, n_run=7) == 7


# ── B4: the gate split (search breadth ≠ evidence thinness) ──────────

class TestGateSearchSizeSplit:
    def _ctx(self, n_trials, search_size, sharpe=0.05, n_bars=800):
        rng = np.random.default_rng(42)
        returns = rng.standard_normal(n_bars) * 0.01 + sharpe / np.sqrt(252)
        return GateContext(
            metrics={"sharpe_annual": sharpe * np.sqrt(252), "exposure_time": 1.0},
            trades=[], returns=returns, equity_curve=[],
            n_trials_global=n_trials, trial_sr_variance=0.01,
            search_size=search_size,
        )

    def test_search_size_drives_the_hurdle(self):
        lo = DeflatedSharpeGate().check(self._ctx(n_trials=50, search_size=0))
        hi = DeflatedSharpeGate().check(self._ctx(n_trials=50, search_size=172_831))
        assert hi.details["search_size"] == 172_831
        assert "search_size" not in lo.details        # OFF path: details byte-identical
        assert hi.details["dsr"] < lo.details["dsr"]  # bigger search → stricter

    def test_gate_refloors_a_lowball_search_size(self):
        # Review fix (B5 defense-in-depth): the gate itself enforces the monotone-stricter
        # floor — a buggy caller supplying search_size < n_trials must not loosen the hurdle.
        low = DeflatedSharpeGate().check(self._ctx(n_trials=50, search_size=5))
        ref = DeflatedSharpeGate().check(self._ctx(n_trials=50, search_size=0))
        assert low.details["search_size"] == 50
        assert low.details["dsr"] == pytest.approx(ref.details["dsr"])

    def test_valves_keep_the_executed_count(self):
        # 1 executed trial → the auto-pass valve fires on EVIDENCE thinness even when the
        # campaign search was huge — breadth must not fake evidence (nor suppress the valve).
        r = DeflatedSharpeGate().check(self._ctx(n_trials=1, search_size=100_000))
        assert r.status == GateStatus.PASS and r.details.get("provisional") is True

    def test_unset_search_size_is_byte_identical_to_today(self):
        a = DeflatedSharpeGate().check(self._ctx(n_trials=50, search_size=0))
        b = DeflatedSharpeGate().check(self._ctx(n_trials=50, search_size=50))
        assert a.details["dsr"] == pytest.approx(b.details["dsr"])
