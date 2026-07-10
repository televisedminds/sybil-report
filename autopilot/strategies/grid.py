"""Grid trading: ladder of resting limit orders around a center price.

Buys as price falls through levels below center, sells inventory as it
rises through levels above — harvesting oscillation inside the band. Grids
earn steadily in sideways markets and are HURT by strong trends: a crash
leaves you fully invested, a rally leaves you in cash. The band recenters
when price escapes it, which realizes that harm rather than hiding it.

Orders are cancelled and re-placed on every candle so the ladder always
matches current cash and inventory.
"""

from __future__ import annotations

from autopilot.execution.orders import BUY, LIMIT, SELL, Cancel, Order
from autopilot.strategies.base import Ctx, Strategy, StrategyError


class GridStrategy(Strategy):
    name = "grid"
    defaults = {
        "levels_per_side": 6,
        "span_pct": 25.0,        # half-width of the band, in percent
        "quote_per_level": 0.0,  # 0 = auto: start equity split across all buy levels
        "recenter_mult": 1.5,    # recenter when |price/center-1| > span * mult
    }
    warmup = 1

    def validate(self):
        if self.p["levels_per_side"] < 1:
            raise StrategyError("grid: levels_per_side must be >= 1")
        if not (0 < self.p["span_pct"] < 95):
            raise StrategyError("grid: span_pct must be in (0, 95)")
        if self.p["quote_per_level"] < 0:
            raise StrategyError("grid: quote_per_level must be >= 0")

    def on_candle(self, ctx: Ctx):
        p = self.p
        levels = int(p["levels_per_side"])
        center = ctx.state.get("center")
        if center is None:
            center = ctx.price
            ctx.state["center"] = center

        drift = abs(ctx.price / center - 1) * 100
        if drift > p["span_pct"] * p["recenter_mult"]:
            center = ctx.price
            ctx.state["center"] = center

        quote_per_level = p["quote_per_level"]
        if quote_per_level <= 0:
            quote_per_level = ctx.state.setdefault(
                "auto_quote", ctx.equity / (levels * 2))

        actions: list = [Cancel(tag="grid")]
        step = p["span_pct"] / levels / 100

        # Buy ladder below price, budgeted by available cash.
        budget = ctx.cash
        for k in range(1, levels + 1):
            level_px = center * (1 - k * step)
            if level_px >= ctx.price or level_px <= 0:
                continue
            spend = min(quote_per_level, budget)
            qty = spend / level_px
            if spend < 1.0 or qty <= 0:
                break
            budget -= spend
            actions.append(Order(side=BUY, otype=LIMIT, base_qty=qty,
                                 limit_price=level_px, tag=f"grid-b{k}"))

        # Sell ladder above price, limited by inventory.
        inventory = ctx.qty
        for k in range(1, levels + 1):
            level_px = center * (1 + k * step)
            if level_px <= ctx.price:
                continue
            qty = min(quote_per_level / level_px, inventory)
            if qty * level_px < 1.0:
                continue
            inventory -= qty
            actions.append(Order(side=SELL, otype=LIMIT, base_qty=qty,
                                 limit_price=level_px, tag=f"grid-s{k}"))

        return actions
