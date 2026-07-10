import unittest

from autopilot.engine.backtest import Backtester
from autopilot.execution.orders import BUY, SELL, Cancel, Order
from autopilot.strategies import StrategyError, make_strategy
from autopilot.strategies.base import Ctx
from autopilot.strategies.indicators import rsi, sma
from tests.helpers import mk_candles


def ctx_for(candles, cash=10_000.0, qty=0.0, state=None):
    price = candles[-1].close
    return Ctx(candles=candles, ts=candles[-1].ts, price=price, cash=cash,
               qty=qty, avg_cost=0.0, equity=cash + qty * price,
               open_orders=[], state=state if state is not None else {})


class IndicatorTests(unittest.TestCase):
    def test_sma(self):
        self.assertIsNone(sma([1, 2], 3))
        self.assertAlmostEqual(sma([1, 2, 3, 4], 2), 3.5)

    def test_rsi_bounds_and_direction(self):
        up = list(range(1, 40))
        down = list(range(40, 1, -1))
        self.assertAlmostEqual(rsi([float(x) for x in up], 14), 100.0)
        self.assertLess(rsi([float(x) for x in down], 14), 5.0)
        self.assertIsNone(rsi([1.0] * 10, 14))


class RegistryTests(unittest.TestCase):
    def test_unknown_strategy(self):
        with self.assertRaises(StrategyError):
            make_strategy("nope")

    def test_unknown_param_rejected(self):
        with self.assertRaises(StrategyError):
            make_strategy("dca", {"typo_param": 1})

    def test_param_validation(self):
        with self.assertRaises(StrategyError):
            make_strategy("sma_cross", {"fast": 200, "slow": 50})
        with self.assertRaises(StrategyError):
            make_strategy("rsi_revert", {"buy_below": 80, "sell_above": 20})
        with self.assertRaises(StrategyError):
            make_strategy("grid", {"span_pct": 200})
        with self.assertRaises(StrategyError):
            make_strategy("dca", {"every": 0})


class DcaTests(unittest.TestCase):
    def test_buys_on_cadence_without_trend_filter(self):
        strat = make_strategy("dca", {"every": 2, "quote_per_buy": 100,
                                      "trend_sma": 0})
        candles = mk_candles([100] * 7)
        state = {}
        buys = 0
        for i in range(1, 8):
            actions = strat.on_candle(ctx_for(candles[:i], state=state))
            buys += sum(1 for a in actions if isinstance(a, Order) and a.side == BUY)
        # first eligible bar buys, then every 2nd bar: bars 1,3,5,7 -> 4 buys
        self.assertEqual(buys, 4)

    def test_trend_filter_blocks_buys_below_sma(self):
        strat = make_strategy("dca", {"every": 1, "quote_per_buy": 100,
                                      "trend_sma": 5})
        candles = mk_candles([100, 100, 100, 100, 100, 50])  # last close < SMA5
        actions = strat.on_candle(ctx_for(candles, state={}))
        self.assertEqual(actions, [])

    def test_sell_on_trend_break(self):
        strat = make_strategy("dca", {"every": 1, "quote_per_buy": 100,
                                      "trend_sma": 5, "sell_on_trend_break": True})
        candles = mk_candles([100, 100, 100, 100, 100, 50])
        actions = strat.on_candle(ctx_for(candles, qty=2.0, state={}))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].side, SELL)
        self.assertAlmostEqual(actions[0].base_qty, 2.0)


class SmaCrossTests(unittest.TestCase):
    def test_enters_when_fast_above_slow(self):
        strat = make_strategy("sma_cross", {"fast": 2, "slow": 4, "target_frac": 1.0})
        rising = mk_candles([100, 110, 120, 130, 140])
        actions = strat.on_candle(ctx_for(rising))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].side, BUY)

    def test_exits_when_fast_below_slow(self):
        strat = make_strategy("sma_cross", {"fast": 2, "slow": 4, "target_frac": 1.0})
        falling = mk_candles([140, 130, 120, 110, 100])
        actions = strat.on_candle(ctx_for(falling, cash=0.0, qty=10.0))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].side, SELL)

    def test_holds_when_already_at_target(self):
        strat = make_strategy("sma_cross", {"fast": 2, "slow": 4, "target_frac": 1.0})
        rising = mk_candles([100, 110, 120, 130, 140])
        price = rising[-1].close
        qty = 10_000.0 / price
        actions = strat.on_candle(ctx_for(rising, cash=0.0, qty=qty))
        self.assertEqual(actions, [])


class RsiRevertTests(unittest.TestCase):
    def test_buys_oversold_sells_recovered(self):
        strat = make_strategy("rsi_revert", {"period": 3, "buy_below": 30,
                                             "sell_above": 55, "target_frac": 1.0})
        crash = mk_candles([100, 90, 80, 70, 60])
        buy_actions = strat.on_candle(ctx_for(crash))
        self.assertEqual(len(buy_actions), 1)
        self.assertEqual(buy_actions[0].side, BUY)

        recover = mk_candles([100, 90, 80, 95, 110, 125])
        sell_actions = strat.on_candle(ctx_for(recover, cash=0.0, qty=5.0))
        self.assertEqual(len(sell_actions), 1)
        self.assertEqual(sell_actions[0].side, SELL)


class GridTests(unittest.TestCase):
    def test_places_symmetric_ladder(self):
        strat = make_strategy("grid", {"levels_per_side": 3, "span_pct": 30,
                                       "quote_per_level": 100})
        candles = mk_candles([100, 100])
        actions = strat.on_candle(ctx_for(candles, cash=1000, qty=3.0))
        cancels = [a for a in actions if isinstance(a, Cancel)]
        buys = [a for a in actions if isinstance(a, Order) and a.side == BUY]
        sells = [a for a in actions if isinstance(a, Order) and a.side == SELL]
        self.assertEqual(len(cancels), 1)
        self.assertEqual(len(buys), 3)
        self.assertEqual(len(sells), 3)
        self.assertTrue(all(o.limit_price < 100 for o in buys))
        self.assertTrue(all(o.limit_price > 100 for o in sells))

    def test_sells_capped_by_inventory(self):
        strat = make_strategy("grid", {"levels_per_side": 4, "span_pct": 20,
                                       "quote_per_level": 1000})
        candles = mk_candles([100, 100])
        actions = strat.on_candle(ctx_for(candles, cash=0.0, qty=2.0))
        sells = [a for a in actions if isinstance(a, Order) and a.side == SELL]
        self.assertLessEqual(sum(o.base_qty for o in sells), 2.0 + 1e-9)

    def test_no_buys_without_cash(self):
        strat = make_strategy("grid", {"levels_per_side": 3, "span_pct": 30,
                                       "quote_per_level": 100})
        candles = mk_candles([100, 100])
        actions = strat.on_candle(ctx_for(candles, cash=0.0, qty=1.0))
        buys = [a for a in actions if isinstance(a, Order) and a.side == BUY]
        self.assertEqual(buys, [])

    def test_recenters_after_breakout(self):
        strat = make_strategy("grid", {"levels_per_side": 3, "span_pct": 10,
                                       "quote_per_level": 100, "recenter_mult": 1.5})
        state = {}
        strat.on_candle(ctx_for(mk_candles([100, 100]), state=state))
        self.assertAlmostEqual(state["center"], 100)
        strat.on_candle(ctx_for(mk_candles([100, 100, 130]), state=state))
        self.assertAlmostEqual(state["center"], 130)


class EndToEndStrategyTests(unittest.TestCase):
    """Full backtests on deterministic shapes — sanity, not performance claims."""

    def test_sma_cross_captures_trend(self):
        closes = [100.0] * 10 + [100.0 + 3 * i for i in range(60)] + [280.0] * 10
        res = Backtester(mk_candles(closes), make_strategy(
            "sma_cross", {"fast": 3, "slow": 8}), start_cash=10_000).run()
        self.assertGreater(res.metrics.total_return_pct, 20)

    def test_grid_harvests_oscillation(self):
        cycle = [100, 95, 90, 95, 100, 105, 110, 105]
        closes = [float(c) for c in cycle * 12]
        res = Backtester(mk_candles(closes), make_strategy(
            "grid", {"levels_per_side": 4, "span_pct": 15}),
            start_cash=10_000, fee_bps=10).run()
        self.assertGreater(res.metrics.n_fills, 10)
        self.assertGreater(res.metrics.total_return_pct, 0)


if __name__ == "__main__":
    unittest.main()
