from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class SlippageType(Enum):
    """Type of slippage calculation."""

    FIXED = "fixed"
    VOLUME_BASED = "volume_based"


@dataclass
class SlippageConfig:
    """Configuration for slippage simulation.

    Attributes:
        type: How slippage is calculated.
        fixed_bps: Fixed slippage in basis points (used when type is FIXED).
        volume_impact: Market-impact factor for volume-based slippage.
            Slippage is proportional to ``volume_impact * sqrt(size / avg_volume)``.
        max_slippage_bps: Maximum slippage cap in basis points.
    """

    type: SlippageType = SlippageType.FIXED
    fixed_bps: float = 2.0  # 2 basis points
    volume_impact: float = 0.1  # impact factor for volume-based
    max_slippage_bps: float = 50.0  # cap


class SlippageModel:
    """Calculates execution price after slippage.

    Supports both a simple fixed basis-point model and a volume-based
    square-root market-impact model.
    """

    def __init__(self, config: SlippageConfig) -> None:
        self.config = config

    def calculate(
        self,
        price: float,
        size: float,
        avg_volume: float | None = None,
    ) -> float:
        """Return the adjusted price after slippage.

        For buy orders (positive *size*) the price increases; for sell
        orders (negative *size*) the price decreases.

        Args:
            price: The intended execution price.
            size: Number of shares/units (sign indicates direction).
            avg_volume: Average daily volume.  Required when
                ``config.type`` is ``VOLUME_BASED``; ignored otherwise.

        Returns:
            The price after applying slippage.
        """
        if self.config.type == SlippageType.FIXED:
            slippage_bps = self.config.fixed_bps
        else:
            # Square-root market-impact model
            if avg_volume is None or avg_volume <= 0:
                slippage_bps = self.config.fixed_bps  # fallback
            else:
                participation = abs(size) / avg_volume
                slippage_bps = self.config.volume_impact * math.sqrt(participation) * 10_000

        # Cap slippage
        slippage_bps = min(slippage_bps, self.config.max_slippage_bps)

        slippage_frac = slippage_bps / 10_000
        direction = 1.0 if size >= 0 else -1.0
        return price * (1.0 + direction * slippage_frac)

    def as_commission_bps(self) -> float:
        """Convert fixed slippage to an equivalent commission fraction.

        Only meaningful for the FIXED model; for volume-based slippage
        this returns the fixed_bps fallback as a rough approximation.

        Returns:
            Slippage cost expressed as a fraction (not basis points).
        """
        return self.config.fixed_bps / 10_000
