from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class CommissionType(Enum):
    """Type of commission calculation."""

    FLAT = "flat"  # fixed amount per trade
    PERCENT = "percent"  # percentage of trade value


@dataclass
class CommissionConfig:
    """Configuration for trade commissions.

    Attributes:
        type: How the commission is calculated.
        value: The commission value (flat amount or percentage, e.g. 0.001 = 0.1%).
        min_fee: Minimum fee charged per trade.
        max_fee: Maximum fee charged per trade.
    """

    type: CommissionType = CommissionType.PERCENT
    value: float = 0.001  # 0.1% default
    min_fee: float = 0.0
    max_fee: float = float("inf")


def commission_callable(config: CommissionConfig) -> Callable[[float, float], float]:
    """Return a callable compatible with backtesting.py's commission parameter.

    The returned function has signature ``(size, price) -> fee`` where *size*
    is the number of shares/units and *price* is the fill price.

    Args:
        config: Commission configuration to use.

    Returns:
        A callable ``(size, price) -> fee``.
    """

    def calc(size: float, price: float) -> float:
        if config.type == CommissionType.FLAT:
            fee = config.value
        else:
            fee = abs(size) * price * config.value
        return max(config.min_fee, min(fee, config.max_fee))

    return calc
