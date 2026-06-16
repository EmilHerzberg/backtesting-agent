"""Quality check for deployment readiness (V3 Teil 4 Step 1).

F-005 fix: The cost-sensitivity and regime-robustness checks were previously
placeholders (``sharpe > 0.7`` and ``wf_ok`` respectively). They are now
replaced with principled, analytic checks that use data already stored on
the trial so the check is cheap and deterministic:

- **Cost sensitivity** — uses the trial's commission + turnover to estimate
  what total return would be at 2× commission, and passes if the
  degradation leaves at least the configured ratio of the original return
  intact. No data re-fetch, no backtest re-run.
- **Regime robustness** — splits the trial's equity curve into quartiles
  and computes rolling returns per quartile. Passes if no quartile drops
  below the configured worst-quartile floor AND the coefficient of
  variation of per-quartile returns is below the configured CoV ceiling.

F-033 fix: The four tunable thresholds are now ENV-configurable so they
can be adjusted per environment without a code change + rebuild. Defaults
preserve the original behavior.
"""
from __future__ import annotations

import os
from statistics import fmean, pstdev
from typing import Any

from sqlalchemy.orm import Session as SyncSession

from backtesting_agent.db.engine import sync_engine


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# F-033 fix: tunable quality-check thresholds.
#
# QC_COST_MIN_RATIO     — minimum fraction of original return that must
#                         survive a 2× commission shock (default 0.5)
# QC_REGIME_WORST_FLOOR — worst single-quartile return allowed (default -0.05)
# QC_REGIME_COV_MAX     — maximum coefficient of variation across the
#                         4 quartiles (default 2.0)
def _cost_min_ratio() -> float:
    return _env_float("QC_COST_MIN_RATIO", 0.5)


def _regime_worst_floor() -> float:
    return _env_float("QC_REGIME_WORST_FLOOR", -0.05)


def _regime_cov_max() -> float:
    return _env_float("QC_REGIME_COV_MAX", 2.0)


def _cost_sensitivity_check(trial: Any) -> tuple[bool, str]:
    """Approximate impact of doubling commission on total return.

    Uses: ``adjusted_return = total_return - commission * turnover``
    where ``turnover`` is the stored trial-level turnover (ratio of traded
    volume to mean equity). Each additional unit of commission costs one
    commission-fraction per unit of turnover — this is the standard
    analytic cost-shock model.

    Passes if adjusted_return remains positive AND retains >= 50% of the
    original return. When turnover is missing we fall back to
    ``2 * commission * trade_count`` as an order-of-magnitude estimate.
    """
    total_return = float(trial.total_return or 0.0)
    commission = float(trial.commission or 0.0)
    turnover = trial.turnover
    trade_count = int(trial.trade_count or 0)

    if total_return <= 0:
        return False, f"Baseline-Return negativ ({total_return*100:.1f}%)"

    if turnover is not None and turnover > 0:
        extra_cost = commission * float(turnover)
        method = f"turnover={float(turnover):.2f}"
    elif trade_count > 0:
        extra_cost = 2.0 * commission * trade_count
        method = f"trades={trade_count}"
    else:
        return False, "Weder Turnover noch Trade-Count verfuegbar"

    adjusted = total_return - extra_cost
    ratio = adjusted / total_return if total_return > 0 else 0.0
    min_ratio = _cost_min_ratio()  # F-033 env-configurable
    passed = adjusted > 0 and ratio >= min_ratio
    detail = (
        f"Return bei 2x Kosten: {adjusted*100:.1f}% "
        f"({ratio*100:.0f}% des Originals, {method})"
    )
    return passed, detail


def _regime_robustness_check(trial: Any, session: SyncSession) -> tuple[bool, str]:
    """Split the trial's equity curve into quartiles and measure stability.

    Passes if no single quartile lost more than 5% AND the coefficient of
    variation (std/mean) across per-quartile returns is below 2.0. This
    catches strategies that made all their money in one regime and
    stagnated/bled in the others.
    """
    from backtesting_agent.results.models import BTEquityCurve

    eq = session.query(BTEquityCurve).filter(BTEquityCurve.trial_id == trial.id).first()
    if eq is None or not eq.values:
        return False, "Keine Equity-Kurve gespeichert"

    values = [float(v) for v in eq.values if v is not None]
    if len(values) < 8:
        return False, f"Equity-Kurve zu kurz ({len(values)} Werte)"

    q = len(values) // 4
    if q < 2:
        return False, "Zu wenige Datenpunkte fuer Quartils-Analyse"

    buckets = [
        values[0:q],
        values[q : 2 * q],
        values[2 * q : 3 * q],
        values[3 * q :],
    ]
    returns: list[float] = []
    for b in buckets:
        if len(b) < 2 or b[0] == 0:
            returns.append(0.0)
        else:
            returns.append((b[-1] / b[0]) - 1.0)

    worst = min(returns)
    mean = fmean(returns)
    std = pstdev(returns) if len(returns) > 1 else 0.0
    # CoV: guard against mean==0 by using abs(mean) in denominator fallback
    cov = abs(std / mean) if abs(mean) > 1e-6 else (float("inf") if std > 0 else 0.0)

    worst_floor = _regime_worst_floor()  # F-033 env-configurable
    cov_max = _regime_cov_max()
    passed = worst > worst_floor and cov < cov_max
    detail = (
        f"Q1..Q4 Returns: {[round(r*100,1) for r in returns]}%, "
        f"Worst={worst*100:.1f}%, CoV={cov:.2f}"
    )
    return passed, detail


def run_quality_check(trial_id: int) -> dict[str, Any]:
    """Run 5 V3-defined checks and return a structured report.

    F-026 fix: returns structured 'not found' response instead of crashing
    when trial doesn't exist. The router maps this to HTTP 404.
    F-005 fix: cost_sensitivity and regime_robustness are now real checks
    (see module docstring).
    """
    from backtesting_agent.results.models import BTTrial

    with SyncSession(sync_engine) as s:
        trial = s.get(BTTrial, trial_id)
        if trial is None:
            return {
                "trial_id": trial_id,
                "ready": False,
                "score": 0,
                "max_score": 5,
                "checks": [],
                "recommendation": "NICHT BEREIT — Trial nicht gefunden",
                "not_found": True,  # F-026 marker for router
            }

        checks: list[dict[str, Any]] = []
        score = 0

        # 1) Walk-Forward validated
        wf_ok = bool(trial.is_validated)
        checks.append(
            {
                "name": "Walk-Forward validiert",
                "passed": wf_ok,
                "detail": "WF-Validierung bestanden" if wf_ok else "Keine WF-Validierung",
                "recommendation": "Walk-Forward-Lauf durchfuehren" if not wf_ok else None,
            }
        )
        if wf_ok:
            score += 1

        # 2) >= 30 trades
        trades_ok = (trial.trade_count or 0) >= 30
        checks.append(
            {
                "name": "Mindestens 30 Trades",
                "passed": trades_ok,
                "detail": f"{trial.trade_count or 0} Trades",
                "recommendation": "Laengeren Zeitraum testen" if not trades_ok else None,
            }
        )
        if trades_ok:
            score += 1

        # 3) Overfitting score > 0.5
        overfit = float(trial.overfitting_score or 0)
        overfit_ok = overfit > 0.5
        checks.append(
            {
                "name": "Overfitting-Score > 0.5",
                "passed": overfit_ok,
                "detail": f"Score: {overfit:.2f}",
                "recommendation": "Strategie ueberdenken — moegliches Overfitting" if not overfit_ok else None,
            }
        )
        if overfit_ok:
            score += 1

        # 4) F-005 fix: real cost sensitivity
        cost_ok, cost_detail = _cost_sensitivity_check(trial)
        checks.append(
            {
                "name": "Kosten-Robustheit (2x Kommission)",
                "passed": cost_ok,
                "detail": cost_detail,
                "recommendation": "Strategie verliert bei doppelten Kosten zu viel Ertrag" if not cost_ok else None,
            }
        )
        if cost_ok:
            score += 1

        # 5) F-005 fix: real regime robustness (per-quartile equity-curve analysis)
        regime_ok, regime_detail = _regime_robustness_check(trial, s)
        checks.append(
            {
                "name": "Zeitraum-Stabilitaet (Quartils-Analyse)",
                "passed": regime_ok,
                "detail": regime_detail,
                "recommendation": "Strategie performt ungleichmaessig ueber verschiedene Zeitabschnitte" if not regime_ok else None,
            }
        )
        if regime_ok:
            score += 1

        if score == 5:
            recommendation = "BEREIT"
            ready = True
        elif score >= 3:
            recommendation = "BEDINGT BEREIT — offene Punkte klaeren"
            ready = True
        else:
            recommendation = "NICHT BEREIT"
            ready = False

        return {
            "trial_id": trial_id,
            "ready": ready,
            "score": score,
            "max_score": 5,
            "checks": checks,
            "recommendation": recommendation,
        }
