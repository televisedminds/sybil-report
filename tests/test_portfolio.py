import unittest

from autopilot.engine.portfolio import Portfolio, PortfolioError, apply_clipped_fill


class PortfolioTests(unittest.TestCase):
    def test_buy_sell_accounting(self):
        p = Portfolio(1000.0)
        p.apply_fill(ts=1, side="buy", qty=2, price=100, fee=0.5)
        self.assertAlmostEqual(p.cash, 1000 - 200 - 0.5)
        self.assertAlmostEqual(p.qty, 2)
        self.assertAlmostEqual(p.avg_cost, 100)

        p.apply_fill(ts=2, side="buy", qty=2, price=200, fee=1.0)
        self.assertAlmostEqual(p.avg_cost, 150)

        fill = p.apply_fill(ts=3, side="sell", qty=4, price=175, fee=0.7)
        self.assertAlmostEqual(fill.realized_pnl, (175 - 150) * 4 - 0.7)
        self.assertEqual(p.qty, 0)
        self.assertEqual(p.avg_cost, 0)
        self.assertAlmostEqual(p.fees_paid, 2.2)

    def test_insufficient_cash_and_position(self):
        p = Portfolio(100.0)
        with self.assertRaises(PortfolioError):
            p.apply_fill(ts=1, side="buy", qty=2, price=100, fee=0)
        with self.assertRaises(PortfolioError):
            p.apply_fill(ts=1, side="sell", qty=1, price=100, fee=0)

    def test_equity_and_exposure(self):
        p = Portfolio(1000.0)
        p.apply_fill(ts=1, side="buy", qty=5, price=100, fee=0)
        self.assertAlmostEqual(p.equity(120), 500 + 600)
        self.assertAlmostEqual(p.exposure_frac(120), 600 / 1100)
        self.assertAlmostEqual(p.unrealized_pnl(120), 100)

    def test_clipped_fill_buy_clips_to_cash(self):
        p = Portfolio(100.0)
        fill = apply_clipped_fill(p, "buy", qty=10, price=50, fee_bps=100,
                                  ts=1, tag="t")
        self.assertIsNotNone(fill)
        self.assertLessEqual(fill.qty * 50 + fill.fee, 100 + 1e-6)
        self.assertGreaterEqual(p.cash, 0)

    def test_clipped_fill_dust_skipped(self):
        p = Portfolio(1000.0)
        self.assertIsNone(apply_clipped_fill(p, "buy", qty=0.00001, price=100,
                                             fee_bps=10, ts=1, tag=""))
        self.assertIsNone(apply_clipped_fill(p, "sell", qty=5, price=100,
                                             fee_bps=10, ts=1, tag=""))  # nothing held


if __name__ == "__main__":
    unittest.main()
