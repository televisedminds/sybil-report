"""Dollar-cost averaging with an optional trend filter.

Buys a fixed cash amount every `every` candles. With `trend_sma` set (e.g.
200 on daily candles), buys only while price is above that moving average —
the classic way to avoid averaging into a collapsing market. Optionally
exits entirely when the trend breaks.

This is an accumulation strategy: `start_cash` is the total budget it will
deploy over time.
"""

from __future__ import annotations

from autopilot.execution.orders import BUY, MARKET, SELL, Order
from autopilot.strategies.base import Ctx, Strategy, StrategyError
from autopilot.strategies.indicators import sma


class DCAStrategy(Strategy):
    name = "dca"
    defaults = {
        "every": 7,                    # buy every N candles
        "quote_per_buy": 200.0,        # cash spent per buy
        "trend_sma": 200,              # 0 disables the filter
        "sell_on_trend_break": False,  # liquidate when close < trend SMA
    }

    def validate(self):
        if self.p["every"] < 1:
            raise StrategyError("dca: 'every' must be >= 1")
        if self.p["quote_per_buy"] <= 0:
            raise StrategyError("dca: 'quote_per_buy' must be positive")
        if self.p["trend_sma"] < 0:
            raise StrategyError("dca: 'trend_sma' must be >= 0")
        self.warmup = max(1, int(self.p["trend_sma"]))

    def on_candle(self, ctx: Ctx):
        p = self.p
        trend_ok = True
        if p["trend_sma"]:
            ma = sma(ctx.closes, int(p["trend_sma"]))
            trend_ok = ma is not None and ctx.price > ma

        if not trend_ok and p["sell_on_trend_break"] and ctx.qty > 0:
            ctx.state["since_buy"] = 0
            return [Order(side=SELL, otype=MARKET, base_qty=ctx.qty, tag="dca-exit")]

        since = ctx.state.get("since_buy", p["every"])  # first eligible bar buys
        since += 1
        if trend_ok and since >= p["every"]:
            amount = min(p["quote_per_buy"], ctx.cash)
            ctx.state["since_buy"] = 0
            if amount > 0:
                return [Order(side=BUY, otype=MARKET, quote_amount=amount, tag="dca-buy")]
            return []
        ctx.state["since_buy"] = since
        return []
