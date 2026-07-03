"""ATS-1748 — Reference CLEAN strategy: simple SMA cross, no look-ahead.

This strategy uses only historical bars (proper lag). It MUST pass the
leakage canary gate.
"""

from __future__ import annotations

import pandas as pd
from backtesting import Strategy


class CleanSMACross(Strategy):
    """Simple SMA crossover using only past bars — no look-ahead."""

    fast_period = 10
    slow_period = 50

    def init(self):
        close = self.data.Close
        self.fast = self.I(
            lambda x: pd.Series(x).rolling(self.fast_period).mean().values,
            close,
            name=f"SMA({self.fast_period})",
        )
        self.slow = self.I(
            lambda x: pd.Series(x).rolling(self.slow_period).mean().values,
            close,
            name=f"SMA({self.slow_period})",
        )

    def next(self):
        # Only uses indicators computed from past bars — clean.
        if self.fast[-1] > self.slow[-1]:
            if not self.position:
                self.buy()
        elif self.fast[-1] < self.slow[-1]:
            if self.position:
                self.position.close()
