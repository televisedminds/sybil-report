import os
import tempfile
import unittest

from autopilot.engine.portfolio import Fill
from autopilot.execution.orders import Order
from autopilot.execution.paper import PaperBroker
from autopilot.runner.state import StateStore
from tests.helpers import T0, mk_candles


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "s.db")
        self.store = StateStore(self.db)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_candles_round_trip_and_upsert(self):
        candles = mk_candles([100, 110, 120])
        self.store.upsert_candles("BTC-USD", "1d", candles)
        self.store.upsert_candles("BTC-USD", "1d", candles)  # idempotent
        loaded = self.store.load_candles("BTC-USD", "1d")
        self.assertEqual(loaded, candles)
        self.assertEqual(self.store.load_candles("BTC-USD", "1d", limit=2),
                         candles[1:])
        self.assertEqual(self.store.load_candles("ETH-USD", "1d"), [])

    def test_fills_equity_events_kv(self):
        self.store.add_fill(Fill(ts=T0, side="buy", qty=1, price=100, fee=0.1))
        self.store.add_equity(T0, 1000, 900, 1, 100)
        self.store.add_equity(T0, 1001, 900, 1, 100)  # replace same ts
        self.store.add_event("test", "hello", level="warn")
        self.assertEqual(len(self.store.load_fills()), 1)
        self.assertEqual(self.store.load_equity(), [(T0, 1001)])
        self.assertEqual(self.store.load_equity_full()[0][1], 1001)
        self.assertEqual(self.store.load_events()[0]["kind"], "test")
        self.store.kv_set("k", {"a": 1})
        self.assertEqual(self.store.kv_get("k"), {"a": 1})
        self.assertEqual(self.store.kv_get("missing", 42), 42)


class PaperBrokerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "p.db")
        self.store = StateStore(self.db)
        self.broker = PaperBroker(self.store, start_cash=10_000,
                                  fee_bps=100, slippage_bps=100)

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_market_buy_with_slippage_and_fee(self):
        fill = self.broker.execute_market(
            Order(side="buy", otype="market", quote_amount=1000), 100.0, T0)
        self.assertIsNotNone(fill)
        self.assertAlmostEqual(fill.price, 101.0)  # 100 bps slippage
        self.assertAlmostEqual(fill.fee, fill.qty * fill.price * 0.01)
        self.assertEqual(len(self.store.load_fills()), 1)

    def test_limit_lifecycle_and_persistence(self):
        self.broker.place_limit(Order(side="buy", otype="limit", base_qty=1,
                                      limit_price=90, tag="grid-b1"), T0)
        self.broker.place_limit(Order(side="sell", otype="limit", base_qty=1,
                                      limit_price=990, tag="grid-s1"), T0)
        self.assertEqual(len(self.broker.open_orders()), 2)

        # nothing crosses at 95
        self.assertEqual(self.broker.check_limit_fills(95.0, T0 + 1), [])
        # buy crosses at 89 -> fills at the limit price 90
        fills = self.broker.check_limit_fills(89.0, T0 + 2)
        self.assertEqual(len(fills), 1)
        self.assertAlmostEqual(fills[0].price, 90.0)
        self.assertEqual(len(self.broker.open_orders()), 1)

        # a new broker on the same DB restores portfolio + open orders
        again = PaperBroker(self.store, start_cash=10_000, fee_bps=100,
                            slippage_bps=100)
        self.assertEqual(len(again.open_orders()), 1)
        self.assertAlmostEqual(again.portfolio.qty, self.broker.portfolio.qty)
        self.assertAlmostEqual(again.portfolio.cash, self.broker.portfolio.cash)

    def test_cancel_by_prefix_and_all(self):
        for tag in ("grid-b1", "grid-b2", "other"):
            self.broker.place_limit(Order(side="buy", otype="limit", base_qty=1,
                                          limit_price=50, tag=tag), T0)
        self.assertEqual(self.broker.cancel("grid"), 2)
        self.assertEqual(self.broker.cancel(""), 1)
        self.assertEqual(self.broker.open_orders(), [])

    def test_sell_without_inventory_skipped(self):
        fill = self.broker.execute_market(
            Order(side="sell", otype="market", base_qty=1), 100.0, T0)
        self.assertIsNone(fill)


if __name__ == "__main__":
    unittest.main()
