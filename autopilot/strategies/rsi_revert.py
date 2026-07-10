"""Mean reversion on RSI (long/flat).

Buys a fixed fraction of equity when RSI drops below `buy_below` (oversold)
and exits once RSI recovers above `sell_above`. Mean reversion harvests
choppy ranges and loses in sustained downtrends — the optional trend filter
(`trend_sma`) keeps it out of falling markets.
"""

from __future__ import annotations

from autopilot.execution.orders import target_position_order
from autopilot.strategies.base import Ctx, Strategy, StrategyError
from autopilot.strategies.indicators import rsi, sma


class RsiRevertStrategy(Strategy):
    name = "rsi_revert"
    defaults = {
        "period": 14,
        "buy_below": 30.0,
        "sell_above": 55.0,
        "target_frac": 0.5,
        "trend_sma": 0,      # 0 disables; e.g. 200 = only buy dips in uptrends
    }

    def validate(self):
        if self.p["period"] < 2:
            raise StrategyError("rsi_revert: period must be >= 2")
        if not (0 <= self.p["buy_below"] < self.p["sell_above"] <= 100):
            raise StrategyError("rsi_revert: need 0 <= buy_below < sell_above <= 100")
        if not (0 < self.p["target_frac"] <= 1):
            raise StrategyError("rsi_revert: target_frac must be in (0, 1]")
        self.warmup = max(int(self.p["period"]) + 1, int(self.p["trend_sma"]))

    def on_candle(self, ctx: Ctx):
        value = rsi(ctx.closes, int(self.p["period"]))
        if value is None:
            return []
        trend_ok = True
        if self.p["trend_sma"]:
            ma = sma(ctx.closes, int(self.p["trend_sma"]))
            trend_ok = ma is not None and ctx.price > ma

        order = None
        if value <= self.p["buy_below"] and trend_ok and ctx.qty == 0:
            order = target_position_order(ctx.equity, ctx.price, ctx.qty, self.p["target_frac"])
        elif value >= self.p["sell_above"] and ctx.qty > 0:
            order = target_position_order(ctx.equity, ctx.price, ctx.qty, 0.0)
        return [order] if order else []
