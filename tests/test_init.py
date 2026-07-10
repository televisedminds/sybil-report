import json
import os
import tempfile
import unittest
from unittest import mock

from autopilot.cli import main
from autopilot.config import Config


class InitWizardTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.dir.name, "cfg.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_yes_writes_valid_default_config(self):
        rc = main(["init", "--yes", "--out", self.out])
        self.assertEqual(rc, 0)
        cfg = Config.load(self.out)
        self.assertEqual(cfg.mode, "paper")
        self.assertEqual(cfg.symbol, "BTC-USD")
        self.assertEqual(cfg.strategy_name, "sma_cross")
        self.assertEqual(cfg.timeframe, "1d")
        self.assertTrue(cfg.state_db.startswith("state/"))

    def test_flags_override_defaults(self):
        rc = main(["init", "--yes", "--out", self.out, "--strategy", "grid",
                   "--symbol", "eth/usd", "--timeframe", "1h",
                   "--cash", "5000", "--port", "9001",
                   "--webhook", "https://example.test/hook"])
        self.assertEqual(rc, 0)
        cfg = Config.load(self.out)
        self.assertEqual(cfg.strategy_name, "grid")
        self.assertEqual(cfg.symbol, "ETH-USD")
        self.assertEqual(cfg.timeframe, "1h")
        self.assertEqual(cfg.start_cash, 5000)
        self.assertEqual(cfg.dashboard_port, 9001)
        self.assertEqual(cfg.webhook_url, "https://example.test/hook")
        self.assertEqual(cfg.strategy_params["quote_per_level"], round(5000 / 12))

    def test_interactive_answers(self):
        answers = iter(["eth-usd", "4", "1h", "2500", "9100", ""])
        with mock.patch("builtins.input", side_effect=lambda *_: next(answers)):
            rc = main(["init", "--out", self.out])
        self.assertEqual(rc, 0)
        cfg = Config.load(self.out)
        self.assertEqual(cfg.symbol, "ETH-USD")
        self.assertEqual(cfg.strategy_name, "grid")
        self.assertEqual(cfg.start_cash, 2500)
        self.assertEqual(cfg.dashboard_port, 9100)
        self.assertIsNone(cfg.webhook_url)

    def test_invalid_answer_reprompts(self):
        answers = iter(["btc-usd", "99", "sma_cross", "1d", "10000", "8899", ""])
        with mock.patch("builtins.input", side_effect=lambda *_: next(answers)):
            rc = main(["init", "--out", self.out])
        self.assertEqual(rc, 0)
        self.assertEqual(Config.load(self.out).strategy_name, "sma_cross")

    def test_refuses_overwrite_without_force(self):
        self.assertEqual(main(["init", "--yes", "--out", self.out]), 0)
        self.assertEqual(main(["init", "--yes", "--out", self.out]), 2)
        self.assertEqual(main(["init", "--yes", "--out", self.out, "--force"]), 0)

    def test_bad_flag_values_rejected(self):
        self.assertEqual(main(["init", "--yes", "--out", self.out,
                               "--strategy", "nope"]), 2)
        self.assertEqual(main(["init", "--yes", "--out", self.out,
                               "--symbol", "BTCUSD"]), 2)

    def test_generated_config_actually_runs(self):
        rc = main(["init", "--yes", "--out", self.out, "--strategy", "dca"])
        self.assertEqual(rc, 0)
        # swap to the offline synthetic source and run 2 loop iterations
        raw = json.load(open(self.out))
        raw["source"] = "synthetic"
        raw["dashboard"]["enabled"] = False
        raw["paper"]["poll_seconds"] = 1
        raw["paper"]["state_db"] = os.path.join(self.dir.name, "s.db")
        raw["strategy"]["params"]["trend_sma"] = 0
        json.dump(raw, open(self.out, "w"))
        self.assertEqual(main(["paper", "--config", self.out,
                               "--iterations", "2"]), 0)


if __name__ == "__main__":
    unittest.main()
