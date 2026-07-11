import os
import tempfile
import unittest

from autopilot.config import Config
from autopilot.execution.broker import BrokerError
from autopilot.execution.live_ccxt import (
    CONFIRM_ENV, CONFIRM_PHRASE, KEY_ENV, SECRET_ENV, LiveBroker,
    assert_live_interlocks, run_live_preflight,
)
from autopilot.execution.orders import Order
from autopilot.runner.state import StateStore
from tests.helpers import mk_candles

GOOD_ENV = {CONFIRM_ENV: CONFIRM_PHRASE, KEY_ENV: "k", SECRET_ENV: "s"}


def live_cfg(cap=200.0, **extra):
    return Config.from_dict({"mode": "live", "live": {"capital_cap": cap},
                             "symbol": "BTC-USD", **extra})


class FakeExchange:
    """Minimal ccxt-shaped stub."""

    def __init__(self, quote_free=1000.0, base_free=0.0,
                 markets=("BTC/USD", "ETH/USD")):
        self.balances = {"USD": quote_free, "BTC": base_free}
        self.orders = []
        self.markets = {m: {} for m in markets}

    def load_markets(self):
        return dict(self.markets)

    def fetch_balance(self):
        return {"free": dict(self.balances)}

    def amount_to_precision(self, symbol, qty):
        return f"{qty:.8f}"

    def create_order(self, symbol, otype, side, qty, price=None):
        self.orders.append((symbol, otype, side, qty, price))
        px = price or 100.0
        if side == "buy":
            self.balances["USD"] -= qty * px
            self.balances["BTC"] += qty
        else:
            self.balances["BTC"] -= qty
            self.balances["USD"] += qty * px
        return {"id": f"o{len(self.orders)}", "average": px, "filled": qty,
                "fee": {"cost": qty * px * 0.001}}

    def fetch_order(self, oid, symbol):
        return {"id": oid, "status": "open"}

    def cancel_order(self, oid, symbol):
        return {}


class InterlockTests(unittest.TestCase):
    def test_all_interlocks_required(self):
        cfg = live_cfg()
        cases = [
            {},                                              # nothing set
            {CONFIRM_ENV: "yes"},                            # wrong phrase
            {CONFIRM_ENV: CONFIRM_PHRASE},                   # no keys
            {CONFIRM_ENV: CONFIRM_PHRASE, KEY_ENV: "k"},     # missing secret
        ]
        for env in cases:
            with self.assertRaises(BrokerError):
                assert_live_interlocks(cfg, env=env)
        assert_live_interlocks(cfg, env=GOOD_ENV)  # passes

    def test_paper_mode_config_rejected(self):
        cfg = Config.from_dict({"mode": "paper"})
        with self.assertRaises(BrokerError):
            assert_live_interlocks(cfg, env=GOOD_ENV)


class LiveBrokerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = StateStore(os.path.join(self.dir.name, "live.db"))

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_capital_cap_bounds_start_cash(self):
        broker = LiveBroker(live_cfg(cap=200), self.store, env=GOOD_ENV,
                            client=FakeExchange(quote_free=1000))
        self.assertEqual(broker.portfolio.start_cash, 200)  # min(1000, cap)

    def test_market_buy_clipped_to_cap_and_recorded(self):
        ex = FakeExchange(quote_free=1000)
        broker = LiveBroker(live_cfg(cap=200), self.store, env=GOOD_ENV, client=ex)
        fill = broker.execute_market(
            Order(side="buy", otype="market", quote_amount=5000), 100.0, 1)
        self.assertIsNotNone(fill)
        self.assertLessEqual(fill.qty * 100.0, 200.0)  # never exceeds the cap
        self.assertEqual(len(ex.orders), 1)
        self.assertEqual(len(self.store.load_fills()), 1)
        self.assertGreater(broker.portfolio.qty, 0)

    def test_limit_place_and_cancel(self):
        ex = FakeExchange()
        broker = LiveBroker(live_cfg(), self.store, env=GOOD_ENV, client=ex)
        oo = broker.place_limit(Order(side="buy", otype="limit", base_qty=0.5,
                                      limit_price=90, tag="grid-b1"), 1)
        self.assertIsNotNone(oo)
        self.assertEqual(len(broker.open_orders()), 1)
        self.assertEqual(broker.check_limit_fills(100.0, 2), [])  # still open
        self.assertEqual(broker.cancel("grid"), 1)
        self.assertEqual(broker.open_orders(), [])

    def test_session_restores_portfolio(self):
        ex = FakeExchange()
        b1 = LiveBroker(live_cfg(), self.store, env=GOOD_ENV, client=ex)
        b1.execute_market(Order(side="buy", otype="market", quote_amount=100),
                          100.0, 1)
        b2 = LiveBroker(live_cfg(), self.store, env=GOOD_ENV, client=ex)
        self.assertAlmostEqual(b2.portfolio.qty, b1.portfolio.qty)


class SyntheticDataSource:
    def fetch(self, symbol, timeframe, start_ms=None, end_ms=None, limit=None):
        return mk_candles([100.0] * (limit or 5))


class PreflightTests(unittest.TestCase):
    def _cfg(self, **extra):
        cfg = live_cfg(**extra)
        cfg.state_db = os.path.join(tempfile.gettempdir(), "preflight-test.db")
        return cfg

    def _run(self, cfg=None, env=GOOD_ENV, client="default"):
        if client == "default":
            client = FakeExchange()
        return run_live_preflight(cfg or self._cfg(), env=env, client=client,
                                  data_source=SyntheticDataSource())

    def test_all_green_with_good_setup(self):
        checks = self._run()
        self.assertTrue(all(c.ok for c in checks),
                        [f"{c.name}: {c.detail}" for c in checks if not c.ok])

    def test_missing_env_fails_interlocks_and_never_trades(self):
        client = FakeExchange()
        checks = run_live_preflight(self._cfg(), env={}, client=client,
                                    data_source=SyntheticDataSource())
        failed = {c.name for c in checks if c.ok is False}
        self.assertTrue(any("confirmation phrase" in n for n in failed))
        self.assertTrue(any("trade-only key" in n for n in failed))
        self.assertEqual(client.orders, [])  # read-only, always

    def test_unlisted_symbol_fails_with_suggestions(self):
        client = FakeExchange(markets=("BTC/EUR", "BTC/USDT"))
        checks = self._run(client=client)
        bad = [c for c in checks if c.ok is False]
        self.assertEqual(len(bad), 1)
        self.assertIn("lists BTC/USD", bad[0].name)
        self.assertIn("BTC/EUR", bad[0].detail)

    def test_tiny_balance_fails_cap_check(self):
        checks = self._run(client=FakeExchange(quote_free=2.0))
        bad = {c.name for c in checks if c.ok is False}
        self.assertIn("quote balance vs capital_cap", bad)

    def test_no_client_skips_venue_checks(self):
        checks = run_live_preflight(self._cfg(), env={CONFIRM_ENV: CONFIRM_PHRASE},
                                    client=None, data_source=SyntheticDataSource())
        # keys missing -> ccxt path can't build a client -> venue checks skipped
        skipped = [c for c in checks if c.ok is None]
        self.assertTrue(any("read balances" in c.name for c in skipped))


if __name__ == "__main__":
    unittest.main()
