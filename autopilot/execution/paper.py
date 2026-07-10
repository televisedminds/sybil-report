"""Paper broker: real market prices, simulated money.

Fill rules mirror the backtester (same helper): slippage on market orders,
fees on everything, cash/position clipping, dust filtering. All activity is
persisted so a session can be killed and resumed without losing state.
"""

from __future__ import annotations

from autopilot.engine.portfolio import Fill, Portfolio, apply_clipped_fill
from autopilot.execution.broker import Broker
from autopilot.execution.orders import BUY, OpenOrder, Order
from autopilot.runner.state import StateStore

KV_PORTFOLIO = "portfolio"
KV_OPEN_ORDERS = "open_orders"


class PaperBroker(Broker):
    def __init__(self, store: StateStore, start_cash: float,
                 fee_bps: float = 25.0, slippage_bps: float = 5.0):
        self.store = store
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.portfolio = Portfolio(start_cash)
        self._open: list[OpenOrder] = []
        self._seq = 0
        self._restore()

    # -- persistence ---------------------------------------------------------

    def _restore(self) -> None:
        saved = self.store.kv_get(KV_PORTFOLIO)
        if saved:
            self.portfolio.restore(
                cash=saved["cash"], qty=saved["qty"], avg_cost=saved["avg_cost"],
                realized_pnl=saved.get("realized_pnl", 0.0),
                fees_paid=saved.get("fees_paid", 0.0))
            self.portfolio.start_cash = saved.get("start_cash", self.portfolio.start_cash)
        for row in self.store.kv_get(KV_OPEN_ORDERS, []) or []:
            self._seq += 1
            self._open.append(OpenOrder(
                order=Order(side=row["side"], otype="limit", base_qty=row["qty"],
                            limit_price=row["limit_price"], tag=row.get("tag", "")),
                placed_ts=row["placed_ts"], id=row.get("id", f"paper-{self._seq}")))

    def _persist(self) -> None:
        p = self.portfolio
        self.store.kv_set(KV_PORTFOLIO, {
            "cash": p.cash, "qty": p.qty, "avg_cost": p.avg_cost,
            "realized_pnl": p.realized_pnl, "fees_paid": p.fees_paid,
            "start_cash": p.start_cash})
        self.store.kv_set(KV_OPEN_ORDERS, [
            {"side": oo.order.side, "qty": oo.order.base_qty,
             "limit_price": oo.order.limit_price, "tag": oo.tag,
             "placed_ts": oo.placed_ts, "id": oo.id}
            for oo in self._open])

    # -- Broker API ------------------------------------------------------------

    def execute_market(self, order: Order, ref_price: float, ts: int) -> Fill | None:
        slip = self.slippage_bps / 10_000
        px = ref_price * (1 + slip if order.side == BUY else 1 - slip)
        fill = apply_clipped_fill(self.portfolio, order.side, order.resolve_qty(px),
                                  px, self.fee_bps, ts, order.tag)
        if fill:
            self.store.add_fill(fill)
        self._persist()
        return fill

    def place_limit(self, order: Order, ts: int) -> OpenOrder:
        self._seq += 1
        oo = OpenOrder(order=order, placed_ts=ts, id=f"paper-{self._seq}")
        self._open.append(oo)
        self._persist()
        return oo

    def cancel(self, tag_prefix: str = "") -> int:
        before = len(self._open)
        if tag_prefix:
            self._open = [oo for oo in self._open if not oo.tag.startswith(tag_prefix)]
        else:
            self._open = []
        self._persist()
        return before - len(self._open)

    def open_orders(self) -> list[OpenOrder]:
        return list(self._open)

    def check_limit_fills(self, last_price: float, ts: int) -> list[Fill]:
        fills: list[Fill] = []
        still: list[OpenOrder] = []
        for oo in self._open:
            o = oo.order
            crossed = (last_price <= o.limit_price if o.side == BUY
                       else last_price >= o.limit_price)
            if not crossed:
                still.append(oo)
                continue
            # Filled at the limit price: for a resting maker order that is the
            # worst (and typical) case.
            fill = apply_clipped_fill(self.portfolio, o.side, o.base_qty,
                                      o.limit_price, self.fee_bps, ts, o.tag)
            if fill:
                fills.append(fill)
                self.store.add_fill(fill)
        self._open = still
        if fills:
            self._persist()
        return fills
