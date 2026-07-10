"""Risk engine: the layer that keeps a strategy from hurting you.

Every order passes through filter_order(); every equity mark passes through
on_equity(). Three independent brakes:

  1. Order caps    — single-order and total-position size limits.
  2. Daily halt    — daily loss beyond the limit stops NEW orders until the
                     next UTC day.
  3. Kill switch   — drawdown from the equity peak beyond the limit halts
                     the session permanently (optionally flattening the
                     position). A human must explicitly `autopilot resume`.

The engine is pure state-in/state-out so it can be persisted and tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from autopilot.config import RiskConfig
from autopilot.execution.orders import BUY, MIN_TRADE_QUOTE, Order


def _utc_day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class RiskEvent:
    kind: str      # "daily_loss_halt" | "kill_switch" | "day_rollover"
    message: str
    level: str = "warn"


class RiskEngine:
    def __init__(self, cfg: RiskConfig, state: dict | None = None):
        self.cfg = cfg
        s = state or {}
        self.day: str | None = s.get("day")
        self.day_start_equity: float | None = s.get("day_start_equity")
        self.orders_today: int = s.get("orders_today", 0)
        self.peak_equity: float | None = s.get("peak_equity")
        self.halted_day: str | None = s.get("halted_day")
        self.killed: bool = s.get("killed", False)
        self.kill_reason: str = s.get("kill_reason", "")

    def to_state(self) -> dict:
        return {
            "day": self.day, "day_start_equity": self.day_start_equity,
            "orders_today": self.orders_today, "peak_equity": self.peak_equity,
            "halted_day": self.halted_day, "killed": self.killed,
            "kill_reason": self.kill_reason,
        }

    # ------------------------------------------------------------------

    def is_halted(self, ts_ms: int) -> bool:
        return self.killed or self.halted_day == _utc_day(ts_ms)

    def status(self, ts_ms: int) -> str:
        if self.killed:
            return f"KILLED ({self.kill_reason})"
        if self.halted_day == _utc_day(ts_ms):
            return "HALTED for the day (daily loss limit)"
        return "active"

    def resume(self) -> None:
        """Human override: clear the kill switch and daily halt."""
        self.killed = False
        self.kill_reason = ""
        self.halted_day = None
        self.peak_equity = None  # restart drawdown measurement from here

    # ------------------------------------------------------------------

    def filter_order(self, order: Order, *, ts_ms: int, equity: float, price: float,
                     position_qty: float) -> tuple[Order | None, str | None]:
        """Return (possibly resized order, None) or (None, reason-blocked).

        Sells are never blocked by size caps — reducing risk is always
        allowed — but they do count against the daily order budget.
        """
        if self.killed:
            return None, f"kill switch engaged: {self.kill_reason}"
        if self.halted_day == _utc_day(ts_ms):
            return None, "halted for the day (daily loss limit)"
        if self.orders_today >= self.cfg.max_orders_per_day:
            return None, f"max_orders_per_day ({self.cfg.max_orders_per_day}) reached"

        result = order
        if order.side == BUY and equity > 0:
            ref = order.limit_price or price
            notional = order.resolve_qty(ref) * ref
            cap_order = equity * self.cfg.max_order_pct / 100
            headroom = equity * self.cfg.max_position_pct / 100 - position_qty * price
            allowed = min(notional, cap_order, max(headroom, 0.0))
            if allowed < MIN_TRADE_QUOTE:
                return None, (f"blocked: order {notional:.2f} exceeds position/order caps "
                              f"(allowed {allowed:.2f})")
            if allowed < notional - 1e-9:
                scale = allowed / notional
                result = Order(
                    side=order.side, otype=order.otype,
                    base_qty=order.base_qty * scale if order.base_qty else None,
                    quote_amount=order.quote_amount * scale if order.quote_amount else None,
                    limit_price=order.limit_price, tag=order.tag)
        self.orders_today += 1
        return result, None

    def on_equity(self, ts_ms: int, equity: float) -> list[RiskEvent]:
        events: list[RiskEvent] = []
        day = _utc_day(ts_ms)
        if day != self.day:
            self.day = day
            self.day_start_equity = equity
            self.orders_today = 0
            events.append(RiskEvent("day_rollover", f"new UTC day {day}, "
                                    f"day-start equity {equity:.2f}", level="info"))
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity

        if (not self.killed and self.peak_equity and self.peak_equity > 0):
            dd = (equity / self.peak_equity - 1) * 100
            if dd <= -self.cfg.max_drawdown_pct:
                self.killed = True
                self.kill_reason = (f"drawdown {dd:.1f}% breached limit "
                                    f"-{self.cfg.max_drawdown_pct}%")
                events.append(RiskEvent("kill_switch", self.kill_reason, level="error"))

        if (not self.killed and self.halted_day != day
                and self.day_start_equity and self.day_start_equity > 0):
            day_pnl = (equity / self.day_start_equity - 1) * 100
            if day_pnl <= -self.cfg.daily_loss_limit_pct:
                self.halted_day = day
                events.append(RiskEvent(
                    "daily_loss_halt",
                    f"day PnL {day_pnl:.1f}% breached limit "
                    f"-{self.cfg.daily_loss_limit_pct}%; no new orders until tomorrow"))
        return events
