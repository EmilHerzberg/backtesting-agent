"""ATS-1747 — Reference LEAKY strategy: peeks at current bar Close.

This strategy deliberately uses look-ahead by reading the current bar's
Close to decide entry. It MUST fail the leakage canary gate.
"""

from __future__ import annotations

from backtesting import Strategy


class LeakyClosePeek(Strategy):
    """Buys when current bar Close > Open (look-ahead leak).

    This is intentionally broken — it sees the close price before the
    bar closes, which is impossible in live trading.
    """

    def init(self):
        pass

    def next(self):
        # LEAK: using self.data.Close[-1] (current bar close) to decide.
        # In real trading, you can't know the close until the bar ends.
        if self.data.Close[-1] > self.data.Open[-1]:
            if not self.position:
                self.buy()
        else:
            if self.position:
                self.position.close()
