"""ATS-1747 / H8 — Reference LEAKY strategy: peeks at the NEXT bar (look-ahead).

The old ``LeakyClosePeek`` read the *current* bar's Close but filled at the next open
(``trade_on_close=False``) — the standard causal pattern, so it did NOT actually leak and could
not fail the canary (review finding H8). This version genuinely leaks: an indicator that at bar t
already knows bar t+1's body (``shift(-1)``). It is long into every bar it KNOWS will close above
its open, so it profits systematically even on zero-drift noise — and MUST fail the leakage canary.
"""

from __future__ import annotations

import pandas as pd
from backtesting import Strategy


class LeakyFuturePeek(Strategy):
    """Look-ahead control: goes long when the NEXT bar is already known to be green.

    Impossible in live trading (you can't see tomorrow's close today). The precomputed indicator
    embeds the future via ``shift(-1)``; backtesting.py trusts the indicator, so the value exposed at
    bar t carries bar t+1's information. Fills at the next open and captures that bar's up-move.
    """

    def init(self):
        # LEAK: next bar's body (close - open), known one bar early via shift(-1).
        self.next_body = self.I(
            lambda o, c: (pd.Series(c).shift(-1) - pd.Series(o).shift(-1)).to_numpy(),
            self.data.Open,
            self.data.Close,
            name="next_bar_body(shift(-1))",
        )

    def next(self):
        if self.next_body[-1] > 0:          # next bar will close above its open → be long into it
            if not self.position:
                self.buy()
        elif self.position:
            self.position.close()
