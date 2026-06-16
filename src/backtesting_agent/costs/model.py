from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from backtesting_agent.costs.commission import (
    CommissionConfig,
    CommissionType,
    commission_callable,
)
from backtesting_agent.costs.slippage import SlippageConfig
from backtesting_agent.costs.spread import SpreadConfig


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
