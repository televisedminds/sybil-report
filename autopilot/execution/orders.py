"""Order intents emitted by strategies and consumed by execution layers."""

from __future__ import annotations

from dataclasses import dataclass, field

BUY, SELL = "buy", "sell"
MARKET, LIMIT = "market", "limit"

# Ignore orders whose notional value is below this (avoids dust churn).
MIN_TRADE_QUOTE = 5.0


@dataclass
class Order:
    """A strategy's intent to trade.

    Market orders size with either base_qty (units of the asset) or
    quote_amount (units of cash). Limit orders require base_qty + limit_price.
    """

    side: str
    otype: str = MARKET
    base_qty: float | None = None
    quote_amount: float | None = None
    limit_price: float | None = None
    tag: str = ""

    def __post_init__(self):
        if self.side not in (BUY, SELL):
            raise ValueError(f"invalid order side {self.side!r}")
        if self.otype not in (MARKET, LIMIT):
            raise ValueError(f"invalid order type {self.otype!r}")
        if self.otype == MARKET:
            if (self.base_qty is None) == (self.quote_amount is None):
                raise ValueError("market order needs exactly one of base_qty / quote_amount")
        else:
            if self.base_qty is None or self.limit_price is None:
                raise ValueError("limit order needs base_qty and limit_price")
            if self.limit_price <= 0:
                raise ValueError("limit_price must be positive")
        for val, name in ((self.base_qty, "base_qty"), (self.quote_amount, "quote_amount")):
            if val is not None and val <= 0:
                raise ValueError(f"{name} must be positive")

    def resolve_qty(self, ref_price: float) -> float:
        """Base quantity this order represents at a reference price."""
        if self.base_qty is not None:
            return self.base_qty
        return (self.quote_amount or 0.0) / ref_price


@dataclass
class Cancel:
    """Cancel open limit orders. Empty tag cancels everything."""

    tag: str = ""


@dataclass
class OpenOrder:
    """A resting limit order tracked by the execution layer."""

    order: Order
    placed_ts: int
    id: str = ""

    @property
    def tag(self) -> str:
        return self.order.tag


def target_position_order(equity: float, price: float, current_qty: float,
                          target_frac: float, min_trade_quote: float = MIN_TRADE_QUOTE,
                          band_frac: float = 0.01) -> Order | None:
    """Market order that moves the position to target_frac of equity.

    Returns None when the adjustment is smaller than the rebalance band
    (band_frac of equity, floored at min_trade_quote). Without the band,
    tiny equity drifts trigger a micro-rebalance on every candle and fees
    quietly eat the account — the band is what makes target-position
    strategies tradeable.
    """
    target_frac = max(0.0, min(1.0, target_frac))
    target_qty = (equity * target_frac) / price if price > 0 else 0.0
    delta = target_qty - current_qty
    threshold = max(min_trade_quote, band_frac * equity)
    if abs(delta) * price < threshold:
        return None
    if delta > 0:
        return Order(side=BUY, otype=MARKET, base_qty=delta, tag="target")
    return Order(side=SELL, otype=MARKET, base_qty=abs(delta), tag="target")
