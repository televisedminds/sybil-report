import math
import unittest

from autopilot.engine.metrics import compute_metrics, max_drawdown_pct
from autopilot.engine.portfolio import Fill

DAY = 86_400_000


class MetricsTests(unittest.TestCase):
    def test_max_drawdown(self):
        self.assertAlmostEqual(max_drawdown_pct([100, 120, 60, 90]), 50.0)
        self.assertEqual(max_drawdown_pct([1, 2, 3]), 0.0)

    def test_flat_curve(self):
        curve = [(i * DAY, 100.0) for i in range(10)]
        m = compute_metrics(curve, [], "1d", 100.0, [1.0] * 10)
        self.assertEqual(m.total_return_pct, 0.0)
        self.assertEqual(m.max_drawdown_pct, 0.0)
        self.assertEqual(m.sharpe, 0.0)

    def test_doubling_year(self):
        curve = [(i * DAY, 100.0 * (2 ** (i / 365))) for i in range(366)]
        m = compute_metrics(curve, [], "1d", 100.0, [])
        self.assertAlmostEqual(m.total_return_pct, 100.0, delta=0.5)
        self.assertAlmostEqual(m.cagr_pct, 100.0, delta=1.5)
        # zero-variance growth: sharpe is defined as 0, not inf
        self.assertEqual(m.sharpe, 0.0)

    def test_sharpe_sign_with_noisy_curves(self):
        up, down = [100.0], [100.0]
        for i in range(200):
            up.append(up[-1] * (1.02 if i % 2 == 0 else 0.995))
            down.append(down[-1] * (0.98 if i % 2 == 0 else 1.005))
        m_up = compute_metrics([(i * DAY, v) for i, v in enumerate(up)],
                               [], "1d", 100.0, [])
        m_down = compute_metrics([(i * DAY, v) for i, v in enumerate(down)],
                                 [], "1d", 100.0, [])
        self.assertGreater(m_up.sharpe, 1)
        self.assertLess(m_down.sharpe, -1)
        self.assertGreater(m_up.volatility_pct, 5)

    def test_benchmark_and_trade_stats(self):
        curve = [(0, 100.0), (DAY, 110.0), (2 * DAY, 105.0)]
        fills = [
            Fill(ts=0, side="buy", qty=1, price=100, fee=0.1),
            Fill(ts=DAY, side="sell", qty=1, price=110, fee=0.1, realized_pnl=9.8),
            Fill(ts=2 * DAY, side="sell", qty=1, price=90, fee=0.1, realized_pnl=-10.1),
        ]
        m = compute_metrics(curve, fills, "1d", 100.0, [50.0, 60.0, 55.0],
                            exposure_flags=[True, True, False])
        self.assertEqual(m.n_fills, 3)
        self.assertEqual(m.n_sells, 2)
        self.assertEqual(m.win_rate_pct, 50.0)
        self.assertAlmostEqual(m.profit_factor, 9.8 / 10.1, places=2)
        self.assertAlmostEqual(m.benchmark_return_pct, 10.0)
        self.assertAlmostEqual(m.exposure_pct, 66.7, delta=0.1)
        self.assertAlmostEqual(m.fees_paid, 0.3, places=6)

    def test_empty_curve_raises(self):
        with self.assertRaises(ValueError):
            compute_metrics([], [], "1d", 100.0, [])


if __name__ == "__main__":
    unittest.main()
