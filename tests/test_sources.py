import unittest
from unittest import mock

from autopilot.data.sources import (
    AutoSource, CoinbaseSource, CSVSource, DataSourceError, KrakenSource,
    SyntheticSource, make_source,
)
from autopilot.data.candles import candles_to_csv
from tests.helpers import mk_candles

COINBASE_PAGE = [  # [ts_s, low, high, open, close, volume], newest first
    [86400 * 2, 95.0, 105.0, 100.0, 102.0, 500.0],
    [86400 * 1, 90.0, 101.0, 99.0, 100.0, 400.0],
]

KRAKEN_PAYLOAD = {
    "error": [],
    "result": {
        "XXBTZUSD": [
            [86400 * 1, "99.0", "101.0", "90.0", "100.0", "99.5", "400.0", 10],
            [86400 * 2, "100.0", "105.0", "95.0", "102.0", "101.0", "500.0", 12],
        ],
        "last": 86400 * 2,
    },
}


class CoinbaseParseTests(unittest.TestCase):
    @mock.patch("autopilot.data.sources.http_get_json", return_value=COINBASE_PAGE)
    def test_parse_and_order(self, _get):
        src = CoinbaseSource()
        candles = src.fetch("BTC-USD", "1d", start_ms=0, end_ms=86400 * 3 * 1000)
        self.assertEqual(len(candles), 2)
        self.assertLess(candles[0].ts, candles[1].ts)  # ascending
        self.assertEqual(candles[1].open, 100.0)
        self.assertEqual(candles[1].high, 105.0)
        self.assertEqual(candles[1].low, 95.0)
        self.assertEqual(candles[1].close, 102.0)

    def test_rejects_unsupported_timeframe(self):
        with self.assertRaises(DataSourceError):
            CoinbaseSource().fetch("BTC-USD", "4h")

    @mock.patch("autopilot.data.sources.http_get_json",
                return_value={"message": "NotFound"})
    def test_error_payload_raises(self, _get):
        with self.assertRaises(DataSourceError):
            CoinbaseSource().fetch("NOPE-USD", "1d", limit=10)


class KrakenParseTests(unittest.TestCase):
    @mock.patch("autopilot.data.sources.http_get_json", return_value=KRAKEN_PAYLOAD)
    def test_parse(self, _get):
        candles = KrakenSource().fetch("BTC-USD", "1d")
        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0].close, 100.0)
        self.assertEqual(candles[0].volume, 400.0)

    def test_pair_mapping(self):
        self.assertEqual(KrakenSource.pair("BTC-USD"), "XBTUSD")
        self.assertEqual(KrakenSource.pair("ETH-USD"), "ETHUSD")

    @mock.patch("autopilot.data.sources.http_get_json",
                return_value={"error": ["EQuery:Unknown asset pair"]})
    def test_error_raises(self, _get):
        with self.assertRaises(DataSourceError):
            KrakenSource().fetch("NOPE-USD", "1d")


class OfflineSourceTests(unittest.TestCase):
    def test_synthetic_deterministic(self):
        a = SyntheticSource(seed=42, n=100).fetch("X-USD", "1d")
        b = SyntheticSource(seed=42, n=100).fetch("X-USD", "1d")
        c = SyntheticSource(seed=43, n=100).fetch("X-USD", "1d")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(all(x.low <= min(x.open, x.close) and
                            x.high >= max(x.open, x.close) for x in a))

    def test_csv_source(self):
        import tempfile, os
        candles = mk_candles([1.0, 2.0, 3.0])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.csv")
            with open(path, "w") as f:
                f.write(candles_to_csv(candles))
            src = CSVSource(path)
            self.assertEqual(src.fetch("X", "1d"), candles)
            self.assertEqual(src.fetch("X", "1d", limit=1), candles[-1:])
            self.assertEqual(src.last_price("X"), 3.0)

    def test_make_source(self):
        self.assertIsInstance(make_source("synthetic", "1d"), SyntheticSource)
        self.assertIsInstance(make_source("auto", "1d"), AutoSource)
        with self.assertRaises(DataSourceError):
            make_source("csv", "1d")  # csv requires path
        with self.assertRaises(DataSourceError):
            make_source("bloomberg", "1d")


class AutoSourceTests(unittest.TestCase):
    def test_falls_back_when_first_source_fails(self):
        auto = AutoSource("1d")
        self.assertEqual([s.name for s in auto.chain], ["coinbase", "kraken"])
        with mock.patch.object(auto.chain[0], "fetch",
                               side_effect=DataSourceError("down")), \
             mock.patch.object(auto.chain[1], "fetch",
                               return_value=mk_candles([1.0])) as krak:
            out = auto.fetch("BTC-USD", "1d", limit=1)
        self.assertEqual(len(out), 1)
        krak.assert_called_once()

    def test_4h_uses_kraken_only(self):
        auto = AutoSource("4h")
        self.assertEqual([s.name for s in auto.chain], ["kraken"])


if __name__ == "__main__":
    unittest.main()
