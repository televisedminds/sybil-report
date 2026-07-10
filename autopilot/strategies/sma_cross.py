"""Trend following via moving-average crossover (long/flat).

Holds `target_frac` of equity while the fast SMA is above the slow SMA,
otherwise holds cash. The classic 50/200 "golden cross". Trend following
trades rarely, catches large moves, and pays for it with whipsaw losses in
sideways markets.
"""

from __future__ import annotations

from autopilot.execution.orders import target_position_order
from autopilot.strategies.base import Ctx, Strategy, StrategyError
from autopilot.strategies.indicators import sma


class SmaCrossStrategy(Strategy):
    name = "sma_cross"
    defaults = {
        "fast": 50,
        "slow": 200,
        "target_frac": 0.95,   # keep a cash buffer for fees
    }

    def validate(self):
        if not (0 < self.p["fast"] < self.p["slow"]):
            raise StrategyError("sma_cross: need 0 < fast < slow")
        if not (0 < self.p["target_frac"] <= 1):
            raise StrategyError("sma_cross: target_frac must be in (0, 1]")
        self.warmup = int(self.p["slow"])

    def on_candle(self, ctx: Ctx):
        fast = sma(ctx.closes, int(self.p["fast"]))
        slow = sma(ctx.closes, int(self.p["slow"]))
        if fast is None or slow is None:
            return []
        frac = self.p["target_frac"] if fast > slow else 0.0
        order = target_position_order(ctx.equity, ctx.price, ctx.qty, frac)
        return [order] if order else []
