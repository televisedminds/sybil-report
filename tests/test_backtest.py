import unittest

from autopilot.engine.backtest import Backtester
from autopilot.execution.orders import Cancel, Order
from autopilot.strategies.base import Strategy
from tests.helpers import mk_candles


class ScriptedStrategy(Strategy):
    """Emits a pre-programmed action list per bar index (for engine tests)."""

    name = "scripted"
    defaults: dict = {}

    def __init__(self, script: dict[int, list]):
        super().__init__({})
        self.script = script

    def on_candle(self, ctx):
        return self.script.get(len(ctx.candles) - 1, [])


class BacktestEngineTests(unittest.TestCase):
    def test_market_fills_next_open_with_slippage_and_fee(self):
        candles = mk_candles([100, 110, 120, 130])
        strat = ScriptedStrategy({0: [Order(side="buy", otype="market", base_qty=1)]})
        res = Backtester(candles, strat, start_cash=1000, fee_bps=100,
                         slippage_bps=100).run()
        self.assertEqual(len(res.fills), 1)
        fill = res.fills[0]
        # signal on bar0 close (100) -> fills at bar1 open (=bar0 close 100) * 1.01
        self.assertAlmostEqual(fill.price, 100 * 1.01)
        self.assertAlmostEqual(fill.fee, fill.qty * fill.price * 0.01)
        self.assertEqual(fill.ts, candles[1].ts)

    def test_no_lookahead_no_same_bar_fill(self):
        candles = mk_candles([100, 200])
        strat = ScriptedStrategy({1: [Order(side="buy", otype="market", base_qty=1)]})
        res = Backtester(candles, strat, start_cash=1000).run()
        self.assertEqual(len(res.fills), 0)  # no bar after the signal -> no fill

    def test_buy_clipped_to_cash(self):
        candles = mk_candles([100, 100, 100])
        strat = ScriptedStrategy({0: [Order(side="buy", otype="market", base_qty=50)]})
        res = Backtester(candles, strat, start_cash=500, fee_bps=0,
                         slippage_bps=0).run()
        self.assertEqual(len(res.fills), 1)
        self.assertLessEqual(res.fills[0].qty * 100, 500 + 1e-6)

    def test_sell_without_position_skipped(self):
        candles = mk_candles([100, 100, 100])
        strat = ScriptedStrategy({0: [Order(side="sell", otype="market", base_qty=1)]})
        res = Backtester(candles, strat, start_cash=500).run()
        self.assertEqual(res.fills, [])

    def test_limit_buy_fills_when_low_crosses(self):
        # bar2 dips to 90: limit buy at 95 must fill at 95 (open above limit)
        candles = mk_candles([100, 100, 95, 100], spread=0.06)
        strat = ScriptedStrategy({0: [Order(side="buy", otype="limit", base_qty=1,
                                            limit_price=95.0)]})
        res = Backtester(candles, strat, start_cash=1000, fee_bps=0,
                         slippage_bps=0).run()
        self.assertEqual(len(res.fills), 1)
        self.assertAlmostEqual(res.fills[0].price, 95.0)

    def test_limit_gap_down_fills_at_open(self):
        # bar2 gaps open below the limit -> favorable fill at the open price
        from autopilot.data.candles import Candle
        from tests.helpers import T0
        day = 86_400_000
        candles = [
            Candle(ts=T0, open=100, high=101, low=99, close=100, volume=1),
            Candle(ts=T0 + day, open=100, high=101, low=99, close=100, volume=1),
            Candle(ts=T0 + 2 * day, open=75, high=82, low=70, close=80, volume=1),
            Candle(ts=T0 + 3 * day, open=80, high=82, low=78, close=81, volume=1),
        ]
        strat = ScriptedStrategy({1: [Order(side="buy", otype="limit", base_qty=1,
                                            limit_price=90.0)]})
        res = Backtester(candles, strat, start_cash=1000, fee_bps=0,
                         slippage_bps=0).run()
        self.assertEqual(len(res.fills), 1)
        self.assertAlmostEqual(res.fills[0].price, 75.0)

    def test_cancel_all_and_prefix(self):
        candles = mk_candles([100] * 5)
        strat = ScriptedStrategy({
            0: [Order(side="buy", otype="limit", base_qty=1, limit_price=10, tag="grid-b1"),
                Order(side="buy", otype="limit", base_qty=1, limit_price=11, tag="other")],
            1: [Cancel(tag="grid")],
            2: [Cancel(tag="")],
        })
        bt = Backtester(candles, strat, start_cash=1000)
        res = bt.run()
        self.assertEqual(res.fills, [])  # nothing ever crossed

    def test_equity_curve_and_benchmark(self):
        candles = mk_candles([100, 110, 121])
        strat = ScriptedStrategy({})
        res = Backtester(candles, strat, start_cash=1000).run()
        self.assertEqual(len(res.equity_curve), 3)
        self.assertTrue(all(eq == 1000 for _, eq in res.equity_curve))
        self.assertAlmostEqual(res.metrics.benchmark_return_pct, 21.0)

    def test_result_serializes(self):
        candles = mk_candles([100, 101, 102])
        strat = ScriptedStrategy({0: [Order(side="buy", otype="market", base_qty=1)]})
        d = Backtester(candles, strat, start_cash=1000).run().to_dict()
        self.assertIn("metrics", d)
        self.assertEqual(len(d["equity_curve"]), 3)
        self.assertEqual(len(d["closes"]), 3)


class LimitGapNoteTests(unittest.TestCase):
    """Pin down the gap-fill rule precisely: open counts, not just the low."""

    def test_open_below_limit_fills_at_open(self):
        candles = mk_candles([100, 100, 80, 80])
        # place at bar1 close; bar2 open == bar1 close == 100 -> NOT below 90;
        # bar2 low is 80 -> fills at the limit 90.
        strat = ScriptedStrategy({1: [Order(side="buy", otype="limit", base_qty=1,
                                            limit_price=90.0)]})
        res = Backtester(candles, strat, start_cash=1000, fee_bps=0,
                         slippage_bps=0).run()
        self.assertEqual(len(res.fills), 1)
        self.assertAlmostEqual(res.fills[0].price, 90.0)


if __name__ == "__main__":
    unittest.main()
