"""Shared test fixtures: deterministic candles, fake clock, fake source."""

from __future__ import annotations

from autopilot.data.candles import Candle, tf_seconds
from autopilot.data.sources import DataSource

T0 = 1_700_000_000_000  # fixed epoch ms origin for tests


def mk_candles(closes: list[float], timeframe: str = "1d", t0: int = T0,
               spread: float = 0.0) -> list[Candle]:
    """Candles where open == previous close and high/low pad by `spread`."""
    step = tf_seconds(timeframe) * 1000
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        hi = max(prev, c) * (1 + spread)
        lo = min(prev, c) * (1 - spread)
        out.append(Candle(ts=t0 + i * step, open=prev, high=hi, low=lo,
                          close=c, volume=1000.0))
        prev = c
    return out


class FakeClock:
    def __init__(self, start_s: float):
        self.t = start_s

    def time(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


class FakeSource(DataSource):
    """Serves a fixed candle list; last_price follows the fake clock."""

    name = "fake"
    supported_timeframes = ("1m", "1h", "1d")

    def __init__(self, candles: list[Candle], timeframe: str, clock: FakeClock):
        self.candles = candles
        self.timeframe = timeframe
        self.clock = clock

    def fetch(self, symbol, timeframe, start_ms=None, end_ms=None, limit=None):
        out = self.candles
        if start_ms:
            out = [c for c in out if c.ts >= start_ms]
        if end_ms:
            out = [c for c in out if c.ts <= end_ms]
        if limit:
            out = out[-limit:]
        return list(out)

    def last_price(self, symbol) -> float:
        now_ms = int(self.clock.time() * 1000)
        step = tf_seconds(self.timeframe) * 1000
        closed = [c for c in self.candles if c.ts + step <= now_ms]
        return closed[-1].close if closed else self.candles[0].open
