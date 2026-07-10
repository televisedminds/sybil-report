"""The trading loop: poll data, decide, risk-check, execute, persist, repeat.

Crash-only design — every step persists its state, so kill -9 at any moment
loses nothing; the next start resumes from the database. Errors in a step
are logged and retried with backoff; the loop only exits on stop(), kill
switch, or max_iterations (used by tests).
"""

from __future__ import annotations

import time

from autopilot.config import Config
from autopilot.data.candles import fmt_ts, is_closed, tf_seconds
from autopilot.data.sources import DataSource, DataSourceError
from autopilot.execution.broker import Broker, BrokerError
from autopilot.execution.orders import Cancel, Order
from autopilot.execution.risk import RiskEngine
from autopilot.runner.notify import Notifier
from autopilot.runner.state import StateStore
from autopilot.strategies.base import Ctx, Strategy

# On restart after downtime, act on at most this many missed candles —
# trading a week of stale signals at today's price would be nonsense.
CATCHUP_LIMIT = 3
HEARTBEAT_SECONDS = 3600
WINDOW_BUFFER = 120  # candles kept beyond strategy warmup


class TradingLoop:
    def __init__(self, cfg: Config, store: StateStore, source: DataSource,
                 strategy: Strategy, broker: Broker, risk: RiskEngine,
                 notifier: Notifier | None = None, clock=time):
        self.cfg = cfg
        self.store = store
        self.source = source
        self.strategy = strategy
        self.broker = broker
        self.risk = risk
        self.notifier = notifier or Notifier(store=store)
        self.clock = clock
        self._stop = False
        self._last_heartbeat = 0.0
        self._consecutive_errors = 0
        self.strategy_state: dict = store.kv_get("strategy_state", {}) or {}
        self.last_processed: int = int(store.kv_get("last_processed_ts", 0) or 0)

    def stop(self, *_args) -> None:
        self._stop = True

    # ------------------------------------------------------------------

    def _window_size(self) -> int:
        return max(self.strategy.warmup, 1) + WINDOW_BUFFER

    def bootstrap(self) -> None:
        """Load enough history and pick the starting point."""
        need = self._window_size()
        have = self.store.load_candles(self.cfg.symbol, self.cfg.timeframe, limit=need)
        if len(have) < need:
            fetched = self.source.fetch(self.cfg.symbol, self.cfg.timeframe, limit=need)
            self.store.upsert_candles(self.cfg.symbol, self.cfg.timeframe, fetched)
            have = self.store.load_candles(self.cfg.symbol, self.cfg.timeframe, limit=need)
        if not have:
            raise DataSourceError(
                f"no candles available for {self.cfg.symbol} {self.cfg.timeframe}")
        if self.last_processed == 0:
            now_ms = int(self.clock.time() * 1000)
            closed = [c for c in have if is_closed(c, self.cfg.timeframe, now_ms)]
            # Fresh session: start trading from the NEXT candle, do not replay history.
            self.last_processed = closed[-1].ts if closed else 0
            self.store.kv_set("last_processed_ts", self.last_processed)
            self.store.add_event(
                "bootstrap",
                f"{len(have)} candles loaded; trading starts after "
                f"{fmt_ts(self.last_processed)} UTC")

    def _ref_price(self, fallback: float) -> float:
        try:
            return self.source.last_price(self.cfg.symbol)
        except DataSourceError:
            return fallback

    def _handle_actions(self, actions, ref_price: float, ts_ms: int) -> list:
        fills = []
        for action in actions or []:
            if isinstance(action, Cancel):
                self.broker.cancel(action.tag)
                continue
            if not isinstance(action, Order):
                continue
            p = self.broker.portfolio
            allowed, reason = self.risk.filter_order(
                action, ts_ms=ts_ms, equity=p.equity(ref_price), price=ref_price,
                position_qty=p.qty)
            if allowed is None:
                self.store.add_event("risk_block", f"{action.side} {action.tag}: {reason}",
                                     level="warn")
                continue
            try:
                if allowed.otype == "market":
                    fill = self.broker.execute_market(allowed, ref_price, ts_ms)
                    if fill:
                        fills.append(fill)
                else:
                    self.broker.place_limit(allowed, ts_ms)
            except BrokerError as e:
                self.store.add_event("broker_error", str(e), level="error")
                self.notifier.send(f"⚠️ broker error: {e}")
        return fills

    def _flatten(self, ref_price: float, ts_ms: int, why: str) -> None:
        self.broker.cancel("")
        qty = self.broker.portfolio.qty
        if qty > 0:
            try:
                self.broker.execute_market(
                    Order(side="sell", otype="market", base_qty=qty, tag="risk-flatten"),
                    ref_price, ts_ms)
            except BrokerError as e:
                self.store.add_event("broker_error", f"flatten failed: {e}", level="error")
        self.notifier.send(f"🛑 KILL SWITCH: {why} — position flattened, trading halted. "
                           f"Investigate, then `autopilot resume` to re-arm.")

    def _summary(self, price: float, ts_ms: int) -> dict:
        p = self.broker.portfolio
        return {
            "mode": self.cfg.mode, "symbol": self.cfg.symbol,
            "timeframe": self.cfg.timeframe, "strategy": self.strategy.describe(),
            "equity": round(p.equity(price), 2), "cash": round(p.cash, 2),
            "qty": p.qty, "avg_cost": round(p.avg_cost, 2), "price": price,
            "realized_pnl": round(p.realized_pnl, 2),
            "unrealized_pnl": round(p.unrealized_pnl(price), 2),
            "fees_paid": round(p.fees_paid, 2),
            "start_cash": p.start_cash,
            "risk": self.risk.status(ts_ms),
            "open_orders": len(self.broker.open_orders()),
            "last_processed": self.last_processed,
            "updated_at": ts_ms,
        }

    # ------------------------------------------------------------------

    def step(self) -> dict:
        """One poll iteration. Returns a summary of what happened."""
        now_ms = int(self.clock.time() * 1000)
        tf = self.cfg.timeframe
        step_ms = tf_seconds(tf) * 1000

        fetched = self.source.fetch(
            self.cfg.symbol, tf, start_ms=self.last_processed - 2 * step_ms
            if self.last_processed else None, limit=self._window_size())
        if fetched:
            self.store.upsert_candles(self.cfg.symbol, tf, fetched)

        window = self.store.load_candles(self.cfg.symbol, tf,
                                         limit=self._window_size() + CATCHUP_LIMIT)
        new_closed = [c for c in window
                      if c.ts > self.last_processed and is_closed(c, tf, now_ms)]
        if len(new_closed) > CATCHUP_LIMIT:
            skipped = len(new_closed) - CATCHUP_LIMIT
            new_closed = new_closed[-CATCHUP_LIMIT:]
            self.store.add_event("catchup_skip",
                                 f"skipped {skipped} stale candles after downtime",
                                 level="warn")

        last_close = window[-1].close if window else 0.0
        ref_price = self._ref_price(last_close)
        fills = []

        for candle in new_closed:
            visible = [c for c in window if c.ts <= candle.ts]
            p = self.broker.portfolio
            ctx = Ctx(candles=visible, ts=candle.ts, price=candle.close,
                      cash=p.cash, qty=p.qty, avg_cost=p.avg_cost,
                      equity=p.equity(candle.close),
                      open_orders=self.broker.open_orders(),
                      state=self.strategy_state)
            actions = self.strategy.on_candle(ctx)
            fills += self._handle_actions(actions, ref_price, now_ms)
            self.last_processed = candle.ts
            self.store.kv_set("last_processed_ts", self.last_processed)
            self.store.kv_set("strategy_state", self.strategy_state)

        fills += self.broker.check_limit_fills(ref_price, now_ms)
        for f in fills:
            msg = (f"{'🟢' if f.side == 'buy' else '🔴'} {self.cfg.mode.upper()} "
                   f"{f.side} {f.qty:.8g} {self.cfg.symbol} @ {f.price:.2f} "
                   f"(fee {f.fee:.2f}"
                   + (f", realized {f.realized_pnl:+.2f}" if f.side == "sell" else "")
                   + ")")
            self.store.add_event("fill", msg)
            self.notifier.send(msg)

        equity = self.broker.portfolio.equity(ref_price)
        for ev in self.risk.on_equity(now_ms, equity):
            self.store.add_event(ev.kind, ev.message, level=ev.level)
            if ev.level in ("warn", "error"):
                self.notifier.send(f"⚠️ {ev.kind}: {ev.message}")
        self.store.kv_set("risk_state", self.risk.to_state())

        killed = self.risk.killed
        if killed and self.cfg.risk.flatten_on_kill and self.broker.portfolio.qty > 0:
            self._flatten(ref_price, now_ms, self.risk.kill_reason)
            equity = self.broker.portfolio.equity(ref_price)

        heartbeat_due = (self.clock.time() - self._last_heartbeat) >= HEARTBEAT_SECONDS
        if new_closed or heartbeat_due:
            p = self.broker.portfolio
            self.store.add_equity(now_ms, equity, p.cash, p.qty, ref_price)
            self._last_heartbeat = self.clock.time()

        summary = self._summary(ref_price, now_ms)
        self.store.kv_set("summary", summary)
        self._consecutive_errors = 0
        return {"new_candles": len(new_closed), "fills": len(fills),
                "equity": equity, "killed": killed, **summary}

    def run(self, max_iterations: int | None = None) -> str:
        self.bootstrap()
        self.store.add_event(
            "start", f"{self.cfg.mode} loop started: {self.cfg.symbol} "
                     f"{self.cfg.timeframe} {self.strategy.describe()}")
        iterations = 0
        reason = "stopped"
        while not self._stop:
            try:
                result = self.step()
                if result["killed"]:
                    reason = "kill_switch"
                    break
            except (DataSourceError, BrokerError, OSError) as e:
                self._consecutive_errors += 1
                self.store.add_event("loop_error",
                                     f"{e} (#{self._consecutive_errors})", level="error")
                if self._consecutive_errors == 5:
                    self.notifier.send(f"⚠️ autopilot: 5 consecutive errors, latest: {e}")
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                reason = "max_iterations"
                break
            # Extra backoff when erroring so we never hammer a failing API.
            delay = self.cfg.poll_seconds * min(self._consecutive_errors + 1, 5)
            deadline = self.clock.time() + delay
            while not self._stop and self.clock.time() < deadline:
                self.clock.sleep(min(1.0, deadline - self.clock.time()))
        self.store.add_event("stop", f"loop exited: {reason}")
        return reason
