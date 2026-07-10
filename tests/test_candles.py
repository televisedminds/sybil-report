import unittest

from autopilot.data.candles import (
    Candle, candles_from_csv, candles_to_csv, dedupe_sorted, is_closed,
    parse_date_ms, tf_seconds,
)


class CandleTests(unittest.TestCase):
    def test_tf_seconds(self):
        self.assertEqual(tf_seconds("1h"), 3600)
        self.assertEqual(tf_seconds("1d"), 86400)
        with self.assertRaises(ValueError):
            tf_seconds("3w")

    def test_parse_date_ms(self):
        self.assertEqual(parse_date_ms("1970-01-02"), 86400_000)
        self.assertEqual(parse_date_ms("1970-01-01T01:00:00+00:00"), 3600_000)
        with self.assertRaises(ValueError):
            parse_date_ms("not-a-date")

    def test_is_closed(self):
        c = Candle(ts=0, open=1, high=1, low=1, close=1, volume=0)
        self.assertTrue(is_closed(c, "1h", 3_600_000))
        self.assertFalse(is_closed(c, "1h", 3_599_999))

    def test_csv_round_trip(self):
        candles = [Candle(ts=i * 1000, open=1.5, high=2.25, low=1.25,
                          close=2.0, volume=10.5) for i in range(3)]
        parsed = candles_from_csv(candles_to_csv(candles))
        self.assertEqual(parsed, candles)

    def test_dedupe_sorted(self):
        a = Candle(ts=2000, open=1, high=1, low=1, close=1, volume=0)
        b = Candle(ts=1000, open=1, high=1, low=1, close=1, volume=0)
        b2 = Candle(ts=1000, open=9, high=9, low=9, close=9, volume=0)
        out = dedupe_sorted([a, b, b2])
        self.assertEqual([c.ts for c in out], [1000, 2000])
        self.assertEqual(out[0].close, 9)  # last write wins


if __name__ == "__main__":
    unittest.main()
