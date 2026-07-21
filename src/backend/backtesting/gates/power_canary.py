"""MON1 — the power canary on the binding (deflated-Sharpe) gate.

Answers, at a RUN's actual operating point: "if a GENUINE edge of the owner's
reference strength existed here, could this gate confirm it?" Measured by
injecting synthetic gaussian return streams with a planted reference edge and
counting firm passes — the same method as the frozen PF1 study, evaluated live.

CONSERVATIVE BY CONSTRUCTION: the canary evaluates at the PF4 null-variance
FLOOR (the smallest V the gate can ever use, i.e. the gate's most generous
possible bar). Power is monotone-decreasing in V, so
    power_at_floor < CANARY_POWER_FLOOR  ⟹  real power < CANARY_POWER_FLOOR
— "vacuous at the floor" proves vacuity outright, with no dependence on the
run's yet-unknown measured dispersion. This is the RT2 precondition evidence:
the advisory stage-1 may only activate when the canary has PROVEN the hard
gate cannot confirm the reference band anyway (softening then relocates
nothing that existed).

Frozen constants mirrored in coverage-v2-gate-config.json + the tamper test.
"""

from __future__ import annotations

import numpy as np

from src.backend.backtesting.gates.deflated_sharpe import DeflatedSharpeGate, deflated_sharpe

CANARY_EDGE = 1.0          # the owner's reference band (D1) — annualized Sharpe
CANARY_HEALTH_EDGE = 6.0   # an absurdly strong edge: if even THIS shows no power
                           # at a small-N point, the canary itself is broken
CANARY_REPS = 200
CANARY_SEED = 20260721
CANARY_POWER_FLOOR = 0.5   # below this at the reference edge = vacuous
_SIGMA_DAILY = 0.01


_HEALTH_T_BARS = 2265      # the health probe's FIXED canonical point: the mechanism
_HEALTH_N = 20             # must show ~full power for an absurd edge HERE, whatever
                           # the run's own window looks like (review fix: probing at
                           # the run's tiny T conflated "broken" with "window small")


def dsr_power_at(edge: float, t_bars: int, n_trials: int, *,
                 sr_variance: float | None = None,
                 reps: int = CANARY_REPS, seed: int = CANARY_SEED) -> float:
    """Firm-pass rate of the DSR bar for a planted annualized edge at the given
    operating point. sr_variance None → the shared PF4 floor (the gate's most
    generous bar — see module doc)."""
    t_bars = max(int(t_bars), 30)
    v = sr_variance if sr_variance is not None else \
        DeflatedSharpeGate.null_variance_floor(t_bars - 1)
    n = max(int(n_trials), 2)
    rng = np.random.default_rng(seed)
    mu = edge / np.sqrt(252.0) * _SIGMA_DAILY
    passes = 0
    for _ in range(int(reps)):
        returns = rng.standard_normal(t_bars) * _SIGMA_DAILY + mu
        if deflated_sharpe(returns, n, v) >= DeflatedSharpeGate.THRESHOLD:
            passes += 1
    return passes / int(reps)


def gate_vacuity_canary(t_bars: int, n_trials: int = 0, *,
                        search_size: int = 0) -> dict:
    """MON1 verdict for one operating point. Returns the evidence dict that is
    recorded wherever the verdict is used (RT2 activation, report, banner).

    RIGOR (review fix): the reference claim is evaluated at N = the firm-verdict
    MINIMUM (PROVISIONAL_BELOW) — power is monotone-DECREASING in N, so the
    smallest firm N gives the MAXIMUM power any real firm verdict can have.
    Together with the floor-V argument, "vacuous here" is a true upper-bound
    proof over every reachable (V, N) — not an artifact of the run's planned
    trial count. The run's own n_trials/search_size are recorded as context.
    """
    n_ref = DeflatedSharpeGate.PROVISIONAL_BELOW
    power_ref = dsr_power_at(CANARY_EDGE, t_bars, n_ref)
    # canary self-health at a FIXED canonical point: an absurd edge must show
    # power there, else the measurement machinery itself is broken and no
    # vacuity claim is honest. Decoupled from the run's window by design.
    health = dsr_power_at(CANARY_HEALTH_EDGE, _HEALTH_T_BARS, _HEALTH_N)
    return {
        "reference_edge": CANARY_EDGE,
        "power_at_reference": round(power_ref, 4),
        "power_floor": CANARY_POWER_FLOOR,
        "canary_healthy": health >= CANARY_POWER_FLOOR,
        "vacuous": bool(health >= CANARY_POWER_FLOOR
                        and power_ref < CANARY_POWER_FLOOR),
        "operating_point": {"t_bars": int(t_bars), "n_reference": n_ref,
                            "run_n_trials": int(n_trials),
                            "run_search_size": int(search_size),
                            "v": "pf4_floor(shared)"},
    }
