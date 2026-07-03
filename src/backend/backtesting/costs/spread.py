from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SpreadConfig:
    """Configuration for bid-ask spread simulation.

    Attributes:
        default_bps: Default half-spread in basis points.
        asset_overrides: Per-asset-class overrides for spread in basis points,
            e.g. ``{"CRYPTO": 20.0, "SMALL_CAP": 15.0}``.
    """

    default_bps: float = 5.0  # 5 basis points default
    asset_overrides: dict[str, float] = field(default_factory=dict)


class SpreadSimulator:
    """Simulates bid-ask spread by adjusting execution prices.

    Buy orders are filled at a slightly higher price and sell orders at a
    slightly lower price to reflect the real-world cost of the spread.
    """

    def __init__(self, config: SpreadConfig) -> None:
        self.config = config

    def adjust_price(
        self,
        price: float,
        side: str,
        asset_class: str = "STOCK",
    ) -> float:
        """Return the effective execution price after applying the spread.

        Args:
            price: The mid-market price.
            side: ``"BUY"`` or ``"SELL"``.
            asset_class: Asset class key used to look up overrides.

        Returns:
            Adjusted price (higher for buys, lower for sells).
        """
        bps = self.config.asset_overrides.get(asset_class, self.config.default_bps)
        spread_half = price * (bps / 10_000) / 2
        if side == "BUY":
            return price + spread_half
        return price - spread_half

    def as_commission_bps(self) -> float:
        """Convert the default spread to an equivalent per-side commission fraction.

        This is useful for feeding into backtesting.py's single commission
        parameter as an approximate cost.

        Returns:
            Spread cost expressed as a fraction (not basis points).
        """
        return self.config.default_bps / 10_000 / 2
