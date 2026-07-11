import json
import os
import tempfile
import unittest
import urllib.request

from autopilot.cli import main
from autopilot.data.candles import candles_to_csv
from autopilot.data.sources import SyntheticSource
from autopilot.runner.state import StateStore
from autopilot.server.dashboard import DashboardServer
from autopilot.server.report import render_report
from tests.helpers import T0


def synthetic_csv(path, n=420, seed=11):
    candles = SyntheticSource(seed=seed, n=n).fetch("X-USD", "1d")
    with open(path, "w", encoding="utf-8") as f:
        f.write(candles_to_csv(candles))
    return path


class CliBacktestTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.csv = synthetic_csv(os.path.join(self.dir.name, "d.csv"))

    def tearDown(self):
        self.dir.cleanup()

    def test_backtest_compare_report_json(self):
        report = os.path.join(self.dir.name, "r.html")
        out_json = os.path.join(self.dir.name, "r.json")
        rc = main(["backtest", "--csv", self.csv, "--symbol", "X-USD",
                   "--strategies", "dca,sma_cross,rsi_revert,grid",
                   "--report", report, "--json", out_json])
        self.assertEqual(rc, 0)
        with open(out_json) as f:
            results = json.load(f)
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertIn("metrics", r)
        html = open(report).read()
        self.assertIn("cmp-chart", html)
        self.assertIn("Read this first", html)
        self.assertNotIn("</script></script>", html)

    def test_backtest_with_params(self):
        rc = main(["backtest", "--csv", self.csv, "--strategy", "dca",
                   "--params", '{"every": 3, "quote_per_buy": 50}'])
        self.assertEqual(rc, 0)

    def test_bad_strategy_errors(self):
        rc = main(["backtest", "--csv", self.csv, "--strategy", "wat"])
        self.assertEqual(rc, 2)

    def test_missing_state_errors(self):
        self.assertEqual(main(["status", "--state", "/nope/x.db"]), 2)
        self.assertEqual(main(["report", "--state", "/nope/x.db"]), 2)
        self.assertEqual(main(["resume", "--state", "/nope/x.db"]), 2)


class CliPaperTests(unittest.TestCase):
    def test_paper_session_runs_offline(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "p.db")
            cfg = {
                "mode": "paper", "symbol": "X-USD", "timeframe": "1d",
                "source": "synthetic",
                "strategy": {"name": "dca", "params": {"every": 1, "trend_sma": 0}},
                "paper": {"poll_seconds": 1, "state_db": db},
                "dashboard": {"enabled": False},
            }
            cfg_path = os.path.join(d, "c.json")
            with open(cfg_path, "w") as f:
                json.dump(cfg, f)
            rc = main(["paper", "--config", cfg_path, "--iterations", "2"])
            self.assertEqual(rc, 0)
            store = StateStore(db)
            self.assertIsNotNone(store.kv_get("summary"))
            self.assertEqual(main(["status", "--state", db]), 0)
            self.assertEqual(main(["resume", "--state", db]), 0)
            store.close()


class ReportRenderTests(unittest.TestCase):
    def test_report_embeds_data_safely(self):
        eq = [[T0 + i * 86_400_000, 100.0 + i] for i in range(5)]
        result = {
            "symbol": "X-USD", "timeframe": "1d",
            "strategy": "dca</script><script>alert(1)",
            "params": {"note": "</script>"}, "start_cash": 100.0,
            "fee_bps": 10.0, "slippage_bps": 5.0,
            "metrics": {
                "total_return_pct": 4.0, "cagr_pct": 300.0, "sharpe": 2.0,
                "sortino": 3.0, "max_drawdown_pct": 1.0, "volatility_pct": 10.0,
                "exposure_pct": 50.0, "n_fills": 2, "win_rate_pct": 100.0,
                "profit_factor": 2.0, "fees_paid": 0.1, "final_equity": 104.0,
                "benchmark_return_pct": 4.0, "benchmark_max_drawdown_pct": 0.0,
            },
            "equity_curve": eq, "closes": [[t, v] for t, v in eq], "fills": [],
        }
        html = render_report([result])
        self.assertNotIn("</script><script>alert", html)
        self.assertIn("Growth of 100", html)


class DashboardServerTests(unittest.TestCase):
    def test_endpoints(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "s.db")
            store = StateStore(db)
            store.kv_set("summary", {"mode": "paper", "symbol": "X-USD",
                                     "equity": 100.0, "updated_at": T0})
            store.add_equity(T0, 100.0, 50.0, 0.5, 100.0)
            store.add_event("test", "hi")
            store.close()

            dash = DashboardServer(db, host="127.0.0.1", port=0)
            dash.start()
            try:
                base = dash.url
                page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
                self.assertIn("Autopilot", page)
                summary = json.loads(urllib.request.urlopen(
                    base + "/api/summary", timeout=5).read())
                self.assertEqual(summary["symbol"], "X-USD")
                equity = json.loads(urllib.request.urlopen(
                    base + "/api/equity?n=10", timeout=5).read())
                self.assertEqual(equity[0][1], 100.0)
                events = json.loads(urllib.request.urlopen(
                    base + "/api/events", timeout=5).read())
                self.assertEqual(events[0]["kind"], "test")
                code = urllib.request.urlopen(base + "/api/trades",
                                              timeout=5).status
                self.assertEqual(code, 200)
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(base + "/nope", timeout=5)
            finally:
                dash.stop()

    def test_token_gate(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "s.db")
            store = StateStore(db)
            store.kv_set("summary", {"symbol": "X-USD"})
            store.close()

            dash = DashboardServer(db, host="127.0.0.1", port=0, token="hunter2")
            dash.start()
            try:
                base = dash.url
                # no token and wrong token -> 401
                for path in ("/", "/api/summary", "/api/summary?token=wrong"):
                    with self.assertRaises(urllib.error.HTTPError) as cm:
                        urllib.request.urlopen(base + path, timeout=5)
                    self.assertEqual(cm.exception.code, 401)
                # right token -> page and API both work
                page = urllib.request.urlopen(
                    base + "/?token=hunter2", timeout=5).read().decode()
                self.assertIn("Autopilot", page)
                summary = json.loads(urllib.request.urlopen(
                    base + "/api/summary?token=hunter2", timeout=5).read())
                self.assertEqual(summary["symbol"], "X-USD")
            finally:
                dash.stop()

    def test_public_bind_requires_token(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "s.db")
            StateStore(db).close()
            with self.assertRaises(ValueError):
                DashboardServer(db, host="0.0.0.0", port=0, token=None)


if __name__ == "__main__":
    unittest.main()
