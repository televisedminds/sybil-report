"""Cash/position accounting shared by backtests, paper trading and live."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Fill:
    ts: int
    side: str  # "buy" | "sell"
    qty: float
    price: float
    fee: float
    tag: str = ""
    realized_pnl: float = 0.0  # net of this fill's fee; buys are 0

    @property
    def notional(self) -> float:
        return self.qty * self.price


class PortfolioError(Exception):
    pass


class Portfolio:
    """Single-asset portfolio with average-cost accounting.

    Buys raise the average cost basis; sells realize PnL against it.
    Fees always come out of cash and are tracked separately.
    """

    def __init__(self, cash: float):
        self.start_cash = cash
        self.cash = cash
        self.qty = 0.0
        self.avg_cost = 0.0
        self.realized_pnl = 0.0
        self.fees_paid = 0.0
        self.fills: list[Fill] = []

    def apply_fill(self, ts: int, side: str, qty: float, price: float,
                   fee: float, tag: str = "") -> Fill:
        if qty <= 0 or price <= 0 or fee < 0:
            raise PortfolioError(f"invalid fill qty={qty} price={price} fee={fee}")
        realized = 0.0
        if side == "buy":
            cost = qty * price
            if cost + fee > self.cash + 1e-9:
                raise PortfolioError(
                    f"insufficient cash: need {cost + fee:.2f}, have {self.cash:.2f}")
            new_qty = self.qty + qty
            self.avg_cost = (self.avg_cost * self.qty + cost) / new_qty
            self.qty = new_qty
            self.cash -= cost + fee
        elif side == "sell":
            if qty > self.qty + 1e-9:
                raise PortfolioError(f"insufficient position: sell {qty}, have {self.qty}")
            qty = min(qty, self.qty)
            realized = (price - self.avg_cost) * qty - fee
            self.qty -= qty
            self.cash += qty * price - fee
            self.realized_pnl += realized
            if self.qty <= 1e-12:
                self.qty = 0.0
                self.avg_cost = 0.0
        else:
            raise PortfolioError(f"invalid side {side!r}")
        self.fees_paid += fee
        fill = Fill(ts=ts, side=side, qty=qty, price=price, fee=fee, tag=tag,
                    realized_pnl=realized)
        self.fills.append(fill)
        return fill

    def equity(self, price: float) -> float:
        return self.cash + self.qty * price

    def exposure_frac(self, price: float) -> float:
        eq = self.equity(price)
        return (self.qty * price) / eq if eq > 0 else 0.0

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_cost) * self.qty if self.qty > 0 else 0.0

    def snapshot(self, price: float) -> dict:
        return {
            "cash": self.cash,
            "qty": self.qty,
            "avg_cost": self.avg_cost,
            "price": price,
            "equity": self.equity(price),
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl(price),
            "fees_paid": self.fees_paid,
        }

    def restore(self, cash: float, qty: float, avg_cost: float,
                realized_pnl: float = 0.0, fees_paid: float = 0.0) -> None:
        """Rehydrate accounting state (used when resuming a persisted session)."""
        self.cash = cash
        self.qty = qty
        self.avg_cost = avg_cost
        self.realized_pnl = realized_pnl
        self.fees_paid = fees_paid


def apply_clipped_fill(portfolio: Portfolio, side: str, qty: float, price: float,
                       fee_bps: float, ts: int, tag: str,
                       min_trade_quote: float = 5.0) -> Fill | None:
    """Fill with cash/position limits and dust filtering applied.

    Buys are clipped to affordable quantity (fee included), sells to the held
    quantity. Returns None when the surviving order is below the dust
    threshold. Used identically by the backtester and the paper broker so
    simulated and paper fills follow the same rules.
    """
    fee_rate = fee_bps / 10_000
    if side == "buy":
        max_qty = portfolio.cash / (price * (1 + fee_rate)) if price > 0 else 0.0
        qty = min(qty, max_qty * 0.99999)  # guard float edge at full allocation
    else:
        qty = min(qty, portfolio.qty)
    if qty <= 0 or qty * price < min_trade_quote:
        return None
    fee = qty * price * fee_rate
    return portfolio.apply_fill(ts=ts, side=side, qty=qty, price=price, fee=fee, tag=tag)
