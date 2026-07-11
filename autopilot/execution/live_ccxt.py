"""Live broker: sends REAL orders to a real exchange via ccxt.

This module refuses to construct unless every interlock passes:

  1. config mode == "live" with live.capital_cap > 0 (hard cash ceiling)
  2. environment AUTOPILOT_LIVE_CONFIRM=I-UNDERSTAND-REAL-MONEY-CAN-BE-LOST
  3. AUTOPILOT_API_KEY / AUTOPILOT_API_SECRET set (never put keys in files)
  4. the optional dependency ccxt is installed  (pip install ccxt)

Use an API key with TRADE permission only — never enable withdrawals.
Run the same config in paper mode for weeks before considering live.
"""

from __future__ import annotations

import importlib
import os

from autopilot.config import Config
from autopilot.engine.portfolio import Fill, Portfolio
from autopilot.execution.broker import Broker, BrokerError
from autopilot.execution.orders import BUY, MIN_TRADE_QUOTE, OpenOrder, Order

CONFIRM_ENV = "AUTOPILOT_LIVE_CONFIRM"
CONFIRM_PHRASE = "I-UNDERSTAND-REAL-MONEY-CAN-BE-LOST"
KEY_ENV, SECRET_ENV = "AUTOPILOT_API_KEY", "AUTOPILOT_API_SECRET"


def assert_live_interlocks(cfg: Config, env: dict | None = None) -> None:
    env = env if env is not None else dict(os.environ)
    problems = []
    if cfg.mode != "live":
        problems.append("config mode is not 'live'")
    if cfg.live_capital_cap <= 0:
        problems.append("live.capital_cap must be a positive hard cash ceiling")
    if env.get(CONFIRM_ENV) != CONFIRM_PHRASE:
        problems.append(f"set {CONFIRM_ENV}={CONFIRM_PHRASE} to confirm you accept the risk")
    if not env.get(KEY_ENV) or not env.get(SECRET_ENV):
        problems.append(f"set {KEY_ENV} and {SECRET_ENV} (trade-only API key, no withdrawal)")
    if problems:
        raise BrokerError("live trading blocked:\n  - " + "\n  - ".join(problems))


def _load_ccxt():
    try:
        return importlib.import_module("ccxt")
    except ImportError:
        raise BrokerError(
            "live trading requires the optional dependency ccxt: pip install ccxt"
        ) from None


# ---------------------------------------------------------------------------
# Preflight: verify the entire live setup WITHOUT placing any order.
# ---------------------------------------------------------------------------

class Check:
    """One preflight check result. ok is True/False, or None if skipped."""

    def __init__(self, name: str, ok: bool | None, detail: str = ""):
        self.name = name
        self.ok = ok
        self.detail = detail

    @property
    def icon(self) -> str:
        return {True: "✅", False: "❌", None: "⏭️ "}[self.ok]


def run_live_preflight(cfg: Config, env: dict | None = None, client=None,
                       data_source=None) -> list[Check]:
    """Read-only verification of a live config: interlocks, keys, venue,
    symbol, balance vs cap, market data. Never sends an order."""
    env = env if env is not None else dict(os.environ)
    checks: list[Check] = []

    checks.append(Check("config mode is 'live' with a positive capital_cap",
                        cfg.mode == "live" and cfg.live_capital_cap > 0,
                        f"mode={cfg.mode}, capital_cap={cfg.live_capital_cap}"))
    checks.append(Check(f"{CONFIRM_ENV} confirmation phrase set",
                        env.get(CONFIRM_ENV) == CONFIRM_PHRASE,
                        "" if env.get(CONFIRM_ENV) == CONFIRM_PHRASE else
                        f"export {CONFIRM_ENV}={CONFIRM_PHRASE}"))
    keys_ok = bool(env.get(KEY_ENV)) and bool(env.get(SECRET_ENV))
    checks.append(Check(f"{KEY_ENV} / {SECRET_ENV} set (trade-only key, "
                        "withdrawals disabled)", keys_ok))

    symbol = cfg.symbol.replace("-", "/")
    if client is None:
        try:
            ccxt = _load_ccxt()
            checks.append(Check("ccxt installed", True,
                                f"version {getattr(ccxt, '__version__', '?')}"))
        except BrokerError as e:
            checks.append(Check("ccxt installed", False, str(e)))
            ccxt = None
        if ccxt is not None:
            exchange_cls = getattr(ccxt, cfg.live_exchange, None)
            checks.append(Check(f"exchange '{cfg.live_exchange}' exists in ccxt",
                                exchange_cls is not None))
            if exchange_cls is not None and keys_ok:
                client = exchange_cls({"apiKey": env.get(KEY_ENV, ""),
                                       "secret": env.get(SECRET_ENV, ""),
                                       "enableRateLimit": True})
    else:
        checks.append(Check("ccxt installed", True, "using injected client"))
        checks.append(Check(f"exchange '{cfg.live_exchange}' exists in ccxt", True,
                            "using injected client"))

    if client is None:
        checks.append(Check(f"exchange lists {symbol}", None, "skipped: no client"))
        checks.append(Check("API key can read balances", None, "skipped: no client"))
        checks.append(Check("quote balance vs capital_cap", None, "skipped: no client"))
    else:
        try:
            markets = client.load_markets()
            listed = symbol in markets
            checks.append(Check(f"exchange lists {symbol}", listed,
                                "" if listed else
                                f"not found; similar: "
                                f"{', '.join(sorted(m for m in markets if m.startswith(symbol.split('/')[0]))[:5]) or 'none'}"))
        except Exception as e:
            checks.append(Check(f"exchange lists {symbol}", False, str(e)))
        try:
            bal = client.fetch_balance()
            quote = cfg.symbol.split("-")[1]
            free = float((bal.get("free") or {}).get(quote) or 0.0)
            checks.append(Check("API key can read balances", True,
                                f"free {quote}: {free:,.2f}"))
            usable = min(free, cfg.live_capital_cap)
            checks.append(Check(
                "quote balance vs capital_cap",
                usable >= MIN_TRADE_QUOTE,
                f"bot will use min(balance, cap) = {usable:,.2f} {quote}"
                + ("" if usable >= MIN_TRADE_QUOTE else
                   f" — below the {MIN_TRADE_QUOTE:.0f} minimum; deposit more first")))
        except Exception as e:
            checks.append(Check("API key can read balances", False, str(e)))
            checks.append(Check("quote balance vs capital_cap", None,
                                "skipped: balance unreadable"))

    if data_source is None:
        from autopilot.data.sources import DataSourceError, make_source
        try:
            data_source = make_source(cfg.source, cfg.timeframe, cfg.csv_path)
        except DataSourceError as e:
            checks.append(Check("market data source reachable", False, str(e)))
            data_source = None
    if data_source is not None:
        try:
            candles = data_source.fetch(cfg.symbol, cfg.timeframe, limit=5)
            checks.append(Check(
                "market data source reachable",
                len(candles) > 0,
                f"{len(candles)} recent {cfg.timeframe} candles for {cfg.symbol}"))
        except Exception as e:
            checks.append(Check("market data source reachable", False, str(e)))

    try:
        os.makedirs(os.path.dirname(os.path.abspath(cfg.state_db)) or ".",
                    exist_ok=True)
        checks.append(Check("state directory writable", True, cfg.state_db))
    except OSError as e:
        checks.append(Check("state directory writable", False, str(e)))

    return checks


class LiveBroker(Broker):
    """Thin, defensive wrapper over a ccxt exchange.

    Keeps a local Portfolio mirror whose cash NEVER exceeds live_capital_cap,
    so the bot cannot deploy more than the configured ceiling regardless of
    what sits in the exchange account.
    """

    def __init__(self, cfg: Config, store, env: dict | None = None, client=None):
        assert_live_interlocks(cfg, env)
        env = env if env is not None else dict(os.environ)
        self.cfg = cfg
        self.store = store
        self.symbol = cfg.symbol.replace("-", "/")
        self.base, self.quote = self.symbol.split("/")
        self.fee_bps = cfg.fee_bps
        if client is None:
            ccxt = _load_ccxt()
            try:
                exchange_cls = getattr(ccxt, cfg.live_exchange)
            except AttributeError:
                raise BrokerError(f"ccxt has no exchange {cfg.live_exchange!r}") from None
            client = exchange_cls({
                "apiKey": env[KEY_ENV], "secret": env[SECRET_ENV],
                "enableRateLimit": True,
            })
        self.client = client
        self._open: list[OpenOrder] = []

        saved = store.kv_get("portfolio")
        if saved:
            self.portfolio = Portfolio(saved.get("start_cash", cfg.live_capital_cap))
            self.portfolio.restore(cash=saved["cash"], qty=saved["qty"],
                                   avg_cost=saved["avg_cost"],
                                   realized_pnl=saved.get("realized_pnl", 0.0),
                                   fees_paid=saved.get("fees_paid", 0.0))
        else:
            free_quote = self._free_balance(self.quote)
            start = min(free_quote, cfg.live_capital_cap)
            if start < MIN_TRADE_QUOTE:
                raise BrokerError(
                    f"exchange {self.quote} balance {free_quote:.2f} below minimum tradeable")
            self.portfolio = Portfolio(start)
            store.add_event("live_start",
                            f"live session started with cash ceiling {start:.2f} {self.quote}")
        self._persist()

    # ------------------------------------------------------------------

    def _free_balance(self, currency: str) -> float:
        try:
            bal = self.client.fetch_balance()
            return float((bal.get("free") or {}).get(currency) or 0.0)
        except Exception as e:
            raise BrokerError(f"fetch_balance failed: {e}") from None

    def _persist(self) -> None:
        p = self.portfolio
        self.store.kv_set("portfolio", {
            "cash": p.cash, "qty": p.qty, "avg_cost": p.avg_cost,
            "realized_pnl": p.realized_pnl, "fees_paid": p.fees_paid,
            "start_cash": p.start_cash})
        self.store.kv_set("open_orders", [
            {"side": oo.order.side, "qty": oo.order.base_qty,
             "limit_price": oo.order.limit_price, "tag": oo.tag,
             "placed_ts": oo.placed_ts, "id": oo.id} for oo in self._open])

    def _precise_qty(self, qty: float) -> float:
        try:
            return float(self.client.amount_to_precision(self.symbol, qty))
        except Exception:
            return round(qty, 8)

    def _record(self, ts: int, side: str, qty: float, price: float, fee: float,
                tag: str) -> Fill:
        fill = self.portfolio.apply_fill(ts=ts, side=side, qty=qty, price=price,
                                         fee=fee, tag=tag)
        self.store.add_fill(fill)
        self._persist()
        return fill

    def _clip(self, side: str, qty: float, price: float) -> float:
        fee_rate = self.fee_bps / 10_000
        if side == BUY:
            max_affordable = self.portfolio.cash / (price * (1 + fee_rate))
            qty = min(qty, max_affordable * 0.999)
        else:
            qty = min(qty, self.portfolio.qty)
        if qty * price < MIN_TRADE_QUOTE:
            return 0.0
        return self._precise_qty(qty)

    # -- Broker API ------------------------------------------------------------

    def execute_market(self, order: Order, ref_price: float, ts: int) -> Fill | None:
        qty = self._clip(order.side, order.resolve_qty(ref_price), ref_price)
        if qty <= 0:
            return None
        try:
            resp = self.client.create_order(self.symbol, "market", order.side, qty)
        except Exception as e:
            raise BrokerError(f"market {order.side} {qty} {self.symbol} failed: {e}") from None
        price = float(resp.get("average") or resp.get("price") or ref_price)
        filled = float(resp.get("filled") or qty)
        fee = self._fee_from(resp, filled * price)
        return self._record(ts, order.side, filled, price, fee, order.tag)

    def _fee_from(self, resp: dict, notional: float) -> float:
        fee = resp.get("fee") or {}
        try:
            cost = float(fee.get("cost"))
            if cost >= 0:
                return cost
        except (TypeError, ValueError):
            pass
        return notional * self.fee_bps / 10_000

    def place_limit(self, order: Order, ts: int) -> OpenOrder | None:
        qty = self._clip(order.side, order.base_qty, order.limit_price)
        if qty <= 0:
            return None
        try:
            resp = self.client.create_order(self.symbol, "limit", order.side, qty,
                                            order.limit_price)
        except Exception as e:
            raise BrokerError(f"limit {order.side} {qty}@{order.limit_price} failed: {e}") from None
        oo = OpenOrder(order=Order(side=order.side, otype="limit", base_qty=qty,
                                   limit_price=order.limit_price, tag=order.tag),
                       placed_ts=ts, id=str(resp.get("id", "")))
        self._open.append(oo)
        self._persist()
        return oo

    def cancel(self, tag_prefix: str = "") -> int:
        doomed = [oo for oo in self._open
                  if not tag_prefix or oo.tag.startswith(tag_prefix)]
        for oo in doomed:
            try:
                self.client.cancel_order(oo.id, self.symbol)
            except Exception as e:
                self.store.add_event("cancel_error", f"{oo.id}: {e}", level="warn")
        self._open = [oo for oo in self._open if oo not in doomed]
        self._persist()
        return len(doomed)

    def open_orders(self) -> list[OpenOrder]:
        return list(self._open)

    def check_limit_fills(self, last_price: float, ts: int) -> list[Fill]:
        fills: list[Fill] = []
        still: list[OpenOrder] = []
        for oo in self._open:
            try:
                resp = self.client.fetch_order(oo.id, self.symbol)
            except Exception as e:
                self.store.add_event("order_poll_error", f"{oo.id}: {e}", level="warn")
                still.append(oo)
                continue
            status = (resp.get("status") or "").lower()
            if status == "closed":
                price = float(resp.get("average") or resp.get("price")
                              or oo.order.limit_price)
                filled = float(resp.get("filled") or oo.order.base_qty)
                fee = self._fee_from(resp, filled * price)
                fills.append(self._record(ts, oo.order.side, filled, price, fee, oo.tag))
            elif status == "canceled":
                continue
            else:
                still.append(oo)
        self._open = still
        if fills:
            self._persist()
        return fills

    def sync(self) -> None:
        """Reconcile the mirror with the exchange (exchange wins on position)."""
        try:
            free_base = self._free_balance(self.base)
        except BrokerError as e:
            self.store.add_event("sync_error", str(e), level="warn")
            return
        drift = abs(free_base - self.portfolio.qty)
        if self.portfolio.qty > 0 and drift / max(self.portfolio.qty, 1e-9) > 0.02 \
                or (self.portfolio.qty == 0 and free_base * 1.0 > 0 and drift > 1e-6):
            self.store.add_event(
                "position_drift",
                f"mirror qty {self.portfolio.qty:.8f} vs exchange free {free_base:.8f}; "
                "adopting exchange value", level="warn")
            self.portfolio.qty = min(self.portfolio.qty, free_base)
            self._persist()
