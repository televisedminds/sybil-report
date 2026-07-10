import unittest

from autopilot.config import RiskConfig
from autopilot.execution.orders import Order
from autopilot.execution.risk import RiskEngine

DAY = 86_400_000
T0 = 1_700_000_000_000  # mid-day UTC anchor


class RiskEngineTests(unittest.TestCase):
    def make(self, **kw):
        cfg = RiskConfig(**{**dict(max_position_pct=50, max_order_pct=10,
                                   daily_loss_limit_pct=5, max_drawdown_pct=20,
                                   max_orders_per_day=3), **kw})
        return RiskEngine(cfg)

    def test_buy_clipped_to_order_cap(self):
        risk = self.make()
        order = Order(side="buy", otype="market", quote_amount=5_000)
        allowed, reason = risk.filter_order(order, ts_ms=T0, equity=10_000,
                                            price=100, position_qty=0)
        self.assertIsNone(reason)
        self.assertAlmostEqual(allowed.quote_amount, 1_000)  # 10% of equity

    def test_buy_blocked_at_position_cap(self):
        risk = self.make()
        # already at 50% of 10k equity -> headroom 0
        order = Order(side="buy", otype="market", quote_amount=500)
        allowed, reason = risk.filter_order(order, ts_ms=T0, equity=10_000,
                                            price=100, position_qty=50)
        self.assertIsNone(allowed)
        self.assertIn("caps", reason)

    def test_sell_never_size_blocked(self):
        risk = self.make()
        order = Order(side="sell", otype="market", base_qty=999)
        allowed, reason = risk.filter_order(order, ts_ms=T0, equity=10_000,
                                            price=100, position_qty=999)
        self.assertIsNotNone(allowed)

    def test_order_budget(self):
        risk = self.make()
        risk.on_equity(T0, 10_000)
        for _ in range(3):
            allowed, _ = risk.filter_order(
                Order(side="buy", otype="market", quote_amount=100),
                ts_ms=T0, equity=10_000, price=100, position_qty=0)
            self.assertIsNotNone(allowed)
        allowed, reason = risk.filter_order(
            Order(side="buy", otype="market", quote_amount=100),
            ts_ms=T0, equity=10_000, price=100, position_qty=0)
        self.assertIsNone(allowed)
        self.assertIn("max_orders_per_day", reason)

    def test_daily_loss_halt_and_rollover(self):
        risk = self.make()
        risk.on_equity(T0, 10_000)
        events = risk.on_equity(T0 + 3_600_000, 9_400)  # -6% intraday
        kinds = [e.kind for e in events]
        self.assertIn("daily_loss_halt", kinds)
        self.assertTrue(risk.is_halted(T0 + 3_600_000))
        allowed, reason = risk.filter_order(
            Order(side="buy", otype="market", quote_amount=10),
            ts_ms=T0 + 3_600_000, equity=9_400, price=100, position_qty=0)
        self.assertIsNone(allowed)
        # next UTC day: halt clears automatically
        events = risk.on_equity(T0 + DAY, 9_400)
        self.assertIn("day_rollover", [e.kind for e in events])
        self.assertFalse(risk.is_halted(T0 + DAY))

    def test_kill_switch_and_resume(self):
        risk = self.make()
        risk.on_equity(T0, 10_000)
        events = risk.on_equity(T0 + DAY, 7_900)  # -21% from peak
        self.assertIn("kill_switch", [e.kind for e in events])
        self.assertTrue(risk.killed)
        # kill switch survives day rollover
        self.assertTrue(risk.is_halted(T0 + 2 * DAY))
        risk.resume()
        self.assertFalse(risk.killed)
        self.assertFalse(risk.is_halted(T0 + 2 * DAY))

    def test_state_round_trip(self):
        risk = self.make()
        risk.on_equity(T0, 10_000)
        risk.on_equity(T0 + DAY, 7_000)
        restored = RiskEngine(risk.cfg, state=risk.to_state())
        self.assertTrue(restored.killed)
        self.assertEqual(restored.kill_reason, risk.kill_reason)


if __name__ == "__main__":
    unittest.main()
