import os
import tempfile
import unittest

from autopilot.config import Config
from autopilot.execution.paper import PaperBroker
from autopilot.execution.risk import RiskEngine
from autopilot.runner.loop import TradingLoop
from autopilot.runner.state import StateStore
from autopilot.strategies import make_strategy
from tests.helpers import T0, FakeClock, FakeSource, mk_candles

MIN = 60_000


def build_loop(tmpdir, closes, clock_start_idx, *, strategy=None, risk_cfg=None,
               poll=30, start_cash=10_000.0):
    """Loop over 1m candles; clock starts just after candle[clock_start_idx] closes."""
    candles = mk_candles(closes, timeframe="1m")
    clock = FakeClock((T0 + (clock_start_idx + 1) * MIN) / 1000 + 1)
    cfg = Config.from_dict({
        "mode": "paper", "symbol": "TEST-USD", "timeframe": "1m",
        "start_cash": start_cash,
        "strategy": {"name": "dca", "params": {"every": 1, "quote_per_buy": 100,
                                               "trend_sma": 0}},
        "risk": risk_cfg or {},
        "paper": {"poll_seconds": poll, "state_db": os.path.join(tmpdir, "loop.db")},
        "dashboard": {"enabled": False},
    })
    store = StateStore(cfg.state_db)
    source = FakeSource(candles, "1m", clock)
    strat = strategy or make_strategy(cfg.strategy_name, cfg.strategy_params)
    broker = PaperBroker(store, cfg.start_cash, cfg.fee_bps, cfg.slippage_bps)
    risk = RiskEngine(cfg.risk, state=store.kv_get("risk_state"))
    loop = TradingLoop(cfg, store, source, strat, broker, risk, clock=clock)
    return loop, store, clock


class TradingLoopTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_bootstrap_starts_from_next_candle(self):
        loop, store, _ = build_loop(self.dir.name, [100.0] * 20, clock_start_idx=15)
        loop.bootstrap()
        self.assertEqual(loop.last_processed, T0 + 15 * MIN)
        # bootstrap alone must place no trades
        self.assertEqual(store.load_fills(), [])

    def test_processes_new_candles_and_buys(self):
        loop, store, clock = build_loop(self.dir.name, [100.0] * 20,
                                        clock_start_idx=15)
        reason = loop.run(max_iterations=8)  # clock advances 30s per iteration
        self.assertEqual(reason, "max_iterations")
        fills = store.load_fills()
        self.assertGreaterEqual(len(fills), 3)  # dca every=1 buys each new candle
        self.assertTrue(all(f.side == "buy" for f in fills))
        self.assertGreater(len(store.load_equity()), 0)
        summary = store.kv_get("summary")
        self.assertEqual(summary["symbol"], "TEST-USD")
        self.assertLess(summary["cash"], 10_000)

    def test_resume_from_persisted_state(self):
        loop, store, clock = build_loop(self.dir.name, [100.0] * 20,
                                        clock_start_idx=15)
        loop.run(max_iterations=4)
        n_fills = len(store.load_fills())
        last = loop.last_processed
        self.assertGreater(n_fills, 0)

        # simulate a crash: fresh loop objects over the same store
        loop2, _, _ = build_loop(self.dir.name, [100.0] * 20, clock_start_idx=15)
        loop2.clock.t = clock.t  # time continues
        loop2.run(max_iterations=4)
        self.assertGreaterEqual(loop2.last_processed, last)
        # no double-processing of already-handled candles
        fills = store.load_fills()
        ts_seen = [f.ts for f in fills]
        self.assertEqual(len(ts_seen), len(set(ts_seen)))

    def test_kill_switch_flattens_and_stops(self):
        closes = [100.0] * 17 + [40.0, 40.0, 40.0]  # crash after buys
        loop, store, clock = build_loop(
            self.dir.name, closes, clock_start_idx=14,
            risk_cfg={"max_drawdown_pct": 20, "max_order_pct": 100,
                      "daily_loss_limit_pct": 99.0},
            strategy=make_strategy("dca", {"every": 1, "quote_per_buy": 5000,
                                           "trend_sma": 0}))
        reason = loop.run(max_iterations=20)
        self.assertEqual(reason, "kill_switch")
        self.assertTrue(loop.risk.killed)
        self.assertEqual(loop.broker.portfolio.qty, 0.0)  # flattened
        kinds = [e["kind"] for e in store.load_events(500)]
        self.assertIn("kill_switch", kinds)
        sells = [f for f in store.load_fills() if f.side == "sell"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0].tag, "risk-flatten")

    def test_catchup_limit_after_long_downtime(self):
        loop, store, _ = build_loop(self.dir.name, [100.0] * 30, clock_start_idx=2)
        loop.bootstrap()
        # jump the clock far ahead: 20+ candles closed while "offline"
        loop.clock.t = (T0 + 29 * MIN) / 1000 + 120
        loop.step()
        kinds = [e["kind"] for e in store.load_events(100)]
        self.assertIn("catchup_skip", kinds)
        # at most CATCHUP_LIMIT candles acted on
        self.assertLessEqual(len(store.load_fills()), 3)


if __name__ == "__main__":
    unittest.main()
