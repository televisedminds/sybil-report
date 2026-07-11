import json
import os
import tempfile
import unittest

from autopilot.config import Config, ConfigError


class ConfigTests(unittest.TestCase):
    def test_defaults_valid(self):
        cfg = Config.from_dict({})
        self.assertEqual(cfg.mode, "paper")
        self.assertEqual(cfg.symbol, "BTC-USD")
        self.assertEqual(cfg.risk.max_drawdown_pct, 30.0)

    def test_full_config(self):
        cfg = Config.from_dict({
            "mode": "paper", "symbol": "eth/usd", "timeframe": "1h",
            "strategy": {"name": "grid", "params": {"span_pct": 20}},
            "risk": {"max_drawdown_pct": 15},
            "paper": {"poll_seconds": 30, "state_db": "x.db"},
            "dashboard": {"port": 9000},
            "notify": {"webhook_url": "https://example.test/hook"},
        })
        self.assertEqual(cfg.symbol, "ETH-USD")  # normalized
        self.assertEqual(cfg.strategy_params, {"span_pct": 20})
        self.assertEqual(cfg.risk.max_drawdown_pct, 15)
        self.assertEqual(cfg.dashboard_port, 9000)

    def test_unknown_key_rejected(self):
        with self.assertRaises(ConfigError):
            Config.from_dict({"strateggy": {}})
        with self.assertRaises(ConfigError):
            Config.from_dict({"risk": {"max_drowdown_pct": 10}})

    def test_underscore_keys_are_comments(self):
        cfg = Config.from_dict({"_README": "note", "risk": {"_note": "x",
                                                            "max_drawdown_pct": 12}})
        self.assertEqual(cfg.risk.max_drawdown_pct, 12)

    def test_bad_values_rejected(self):
        with self.assertRaises(ConfigError):
            Config.from_dict({"mode": "yolo"})
        with self.assertRaises(ConfigError):
            Config.from_dict({"timeframe": "13m"})
        with self.assertRaises(ConfigError):
            Config.from_dict({"start_cash": -5})
        with self.assertRaises(ConfigError):
            Config.from_dict({"symbol": "BTCUSD"})

    def test_live_requires_capital_cap(self):
        with self.assertRaises(ConfigError) as cm:
            Config.from_dict({"mode": "live"})
        self.assertIn("capital_cap", str(cm.exception))
        cfg = Config.from_dict({"mode": "live", "live": {"capital_cap": 250}})
        self.assertEqual(cfg.live_capital_cap, 250)

    def test_csv_source_requires_path(self):
        with self.assertRaises(ConfigError):
            Config.from_dict({"source": "csv"})

    def test_public_dashboard_requires_token(self):
        with self.assertRaises(ConfigError):
            Config.from_dict({"dashboard": {"host": "0.0.0.0"}})
        cfg = Config.from_dict({"dashboard": {"host": "0.0.0.0",
                                              "token": "secret-word"}})
        self.assertEqual(cfg.dashboard_token, "secret-word")

    def test_load_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            with open(path, "w") as f:
                json.dump({"mode": "paper", "symbol": "BTC-USD"}, f)
            cfg = Config.load(path)
            self.assertEqual(cfg.symbol, "BTC-USD")
            with open(path, "w") as f:
                f.write("{broken")
            with self.assertRaises(ConfigError):
                Config.load(path)
            with self.assertRaises(ConfigError):
                Config.load(os.path.join(d, "missing.json"))


if __name__ == "__main__":
    unittest.main()
