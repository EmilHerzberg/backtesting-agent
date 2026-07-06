from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.backend.backtesting.costs.commission import (
    CommissionConfig,
    CommissionType,
    commission_callable,
)
from src.backend.backtesting.costs.slippage import SlippageConfig
from src.backend.backtesting.costs.spread import SpreadConfig


def effective_commission_pct(
    commission_pct: float = 0.001, spread_bps: float = 5.0, slippage_bps: float = 2.0
) -> float:
    """H29/D8 — the SINGLE effective per-side cost fraction shared by the CLI and the AI research
    executor: percentage commission + HALF the bid-ask spread (one side crossed per fill) + slippage.

    Previously the CLI charged ~14.5 bps/side (commission 0.1% + 2.5 bps half-spread + 2 bps slippage)
    while ResearchExecutor charged a bare 0.1% (10 bps), so AI-discovered strategies were evaluated at
    ~30% lower transaction cost than the platform's own documented model and every cost-sensitive gate
    stressed the thinner baseline. Both paths now derive their commission from this one helper."""
    return float(commission_pct) + float(spread_bps) / 10_000 / 2 + float(slippage_bps) / 10_000


@dataclass
class CostConfig:
    """Combined cost model aggregating commission, spread, and slippage.

    Provides helpers to collapse all costs into a single percentage or
    callable that can be plugged directly into backtesting.py.

    Attributes:
        commission: Commission configuration.
        spread: Bid-ask spread configuration.
        slippage: Slippage configuration.
    """

    commission: CommissionConfig = field(default_factory=CommissionConfig)
    spread: SpreadConfig = field(default_factory=SpreadConfig)
    slippage: SlippageConfig = field(default_factory=SlippageConfig)

    def total_commission_pct(self) -> float:
        """Return the combined cost as a single per-trade percentage.

        This is a convenience approximation that sums:
        - percentage-based commission (if applicable),
        - half-spread (one side of the bid-ask),
        - fixed slippage.

        Useful for feeding into backtesting.py's ``commission`` parameter
        when a single scalar is sufficient.

        Returns:
            Combined cost fraction (e.g. 0.0015 means 0.15%).
        """
        comm = (
            self.commission.value
            if self.commission.type == CommissionType.PERCENT
            else 0.0
        )
        spread = self.spread.default_bps / 10_000 / 2
        slip = self.slippage.fixed_bps / 10_000
        return comm + spread + slip

    def as_callable(self) -> Callable[[float, float], float]:
        """Return a ``(size, price) -> fee`` callable for backtesting.py.

        The fee includes commission, spread cost, and slippage cost,
        all expressed in absolute currency.

        Returns:
            A callable compatible with backtesting.py's commission parameter.
        """
        base_callable = commission_callable(self.commission)
        spread_frac = self.spread.default_bps / 10_000 / 2
        slip_frac = self.slippage.fixed_bps / 10_000

        def calc(size: float, price: float) -> float:
            commission_fee = base_callable(size, price)
            trade_value = abs(size) * price
            spread_fee = trade_value * spread_frac
            slip_fee = trade_value * slip_frac
            return commission_fee + spread_fee + slip_fee

        return calc
