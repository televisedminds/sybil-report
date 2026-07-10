"""Market data sources.

Free, keyless public endpoints (Coinbase Exchange, Kraken) plus CSV and a
deterministic synthetic generator for offline work and tests. Every source
returns ascending, de-duplicated candle lists.
"""

from __future__ import annotations

import json
import math
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from autopilot.data.candles import Candle, dedupe_sorted, candles_from_csv, tf_seconds

USER_AGENT = "autopilot/0.1 (self-hosted research tool)"
HTTP_TIMEOUT = 20
HTTP_RETRIES = 4


class DataSourceError(Exception):
    pass


def http_get_json(url: str, retries: int = HTTP_RETRIES, timeout: int = HTTP_TIMEOUT):
    """GET a JSON document with retries and exponential backoff."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(min(2**attempt, 8))
    raise DataSourceError(f"GET {url} failed after {retries} attempts: {last_err}")


class DataSource:
    """Interface: fetch historical candles and the latest spot price."""

    name = "base"
    supported_timeframes: tuple[str, ...] = ()

    def fetch(self, symbol: str, timeframe: str, start_ms: int | None = None,
              end_ms: int | None = None, limit: int | None = None) -> list[Candle]:
        raise NotImplementedError

    def last_price(self, symbol: str) -> float:
        raise NotImplementedError

    def supports(self, timeframe: str) -> bool:
        return timeframe in self.supported_timeframes


# ---------------------------------------------------------------------------
# Coinbase Exchange (public, keyless). Candle rows: [ts_s, low, high, open, close, volume]
# newest-first, max 300 per request.
# ---------------------------------------------------------------------------

class CoinbaseSource(DataSource):
    name = "coinbase"
    BASE = "https://api.exchange.coinbase.com"
    GRANULARITY = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}
    supported_timeframes = tuple(GRANULARITY)
    PAGE = 300

    @staticmethod
    def product(symbol: str) -> str:
        return symbol.upper().replace("/", "-")

    def _fetch_page(self, symbol: str, timeframe: str, start_ms: int, end_ms: int) -> list[Candle]:
        gran = self.GRANULARITY[timeframe]
        params = urllib.parse.urlencode({
            "granularity": gran,
            "start": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
            "end": datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat(),
        })
        url = f"{self.BASE}/products/{self.product(symbol)}/candles?{params}"
        raw = http_get_json(url)
        if not isinstance(raw, list):
            raise DataSourceError(f"coinbase: unexpected response for {symbol}: {raw!r}")
        return [
            Candle(ts=int(r[0]) * 1000, open=float(r[3]), high=float(r[2]),
                   low=float(r[1]), close=float(r[4]), volume=float(r[5]))
            for r in raw
        ]

    def fetch(self, symbol, timeframe, start_ms=None, end_ms=None, limit=None):
        if timeframe not in self.GRANULARITY:
            raise DataSourceError(f"coinbase does not support timeframe {timeframe}")
        step_ms = tf_seconds(timeframe) * 1000
        now_ms = int(time.time() * 1000)
        end_ms = end_ms or now_ms
        if start_ms is None:
            n = limit or self.PAGE
            start_ms = end_ms - n * step_ms
        out: list[Candle] = []
        cursor_end = end_ms
        # Paginate backwards through history, 300 candles per request.
        while cursor_end > start_ms:
            cursor_start = max(start_ms, cursor_end - self.PAGE * step_ms)
            page = self._fetch_page(symbol, timeframe, cursor_start, cursor_end)
            out.extend(page)
            if cursor_start <= start_ms:
                break
            cursor_end = cursor_start
            time.sleep(0.35)  # stay well under public rate limits
        candles = [c for c in dedupe_sorted(out) if c.ts >= start_ms and c.ts <= end_ms]
        if limit:
            candles = candles[-limit:]
        return candles

    def last_price(self, symbol: str) -> float:
        url = f"{self.BASE}/products/{self.product(symbol)}/ticker"
        raw = http_get_json(url)
        try:
            return float(raw["price"])
        except (KeyError, TypeError, ValueError):
            raise DataSourceError(f"coinbase: no ticker price for {symbol}: {raw!r}") from None


# ---------------------------------------------------------------------------
# Kraken (public, keyless). Returns at most the latest 720 candles per
# timeframe, ascending: [ts_s, open, high, low, close, vwap, volume, count]
# ---------------------------------------------------------------------------

class KrakenSource(DataSource):
    name = "kraken"
    BASE = "https://api.kraken.com/0/public"
    INTERVAL = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    supported_timeframes = tuple(INTERVAL)

    @staticmethod
    def pair(symbol: str) -> str:
        base, _, quote = symbol.upper().replace("/", "-").partition("-")
        base = {"BTC": "XBT"}.get(base, base)
        return f"{base}{quote}"

    def _result(self, raw, what: str):
        if not isinstance(raw, dict) or raw.get("error"):
            raise DataSourceError(f"kraken: {what} error: {raw!r}")
        result = raw.get("result") or {}
        keys = [k for k in result if k != "last"]
        if not keys:
            raise DataSourceError(f"kraken: empty {what} result: {raw!r}")
        return result[keys[0]]

    def fetch(self, symbol, timeframe, start_ms=None, end_ms=None, limit=None):
        if timeframe not in self.INTERVAL:
            raise DataSourceError(f"kraken does not support timeframe {timeframe}")
        params = {"pair": self.pair(symbol), "interval": self.INTERVAL[timeframe]}
        if start_ms:
            params["since"] = start_ms // 1000 - 1
        url = f"{self.BASE}/OHLC?{urllib.parse.urlencode(params)}"
        rows = self._result(http_get_json(url), "OHLC")
        candles = [
            Candle(ts=int(r[0]) * 1000, open=float(r[1]), high=float(r[2]),
                   low=float(r[3]), close=float(r[4]), volume=float(r[6]))
            for r in rows
        ]
        candles = dedupe_sorted(candles)
        if start_ms:
            candles = [c for c in candles if c.ts >= start_ms]
        if end_ms:
            candles = [c for c in candles if c.ts <= end_ms]
        if limit:
            candles = candles[-limit:]
        return candles

    def last_price(self, symbol: str) -> float:
        url = f"{self.BASE}/Ticker?pair={self.pair(symbol)}"
        data = self._result(http_get_json(url), "Ticker")
        try:
            return float(data["c"][0])
        except (KeyError, TypeError, ValueError, IndexError):
            raise DataSourceError(f"kraken: no ticker price for {symbol}") from None


# ---------------------------------------------------------------------------
# Offline sources
# ---------------------------------------------------------------------------

class CSVSource(DataSource):
    """Reads candles from a CSV file (ts_ms,open,high,low,close,volume)."""

    name = "csv"
    supported_timeframes = tuple(tf for tf in ("1m", "5m", "15m", "1h", "4h", "6h", "1d"))

    def __init__(self, path: str):
        self.path = path
        self._cache: list[Candle] | None = None

    def _load(self) -> list[Candle]:
        if self._cache is None:
            try:
                with open(self.path, encoding="utf-8") as f:
                    self._cache = candles_from_csv(f.read())
            except OSError as e:
                raise DataSourceError(f"csv: cannot read {self.path}: {e}") from None
            if not self._cache:
                raise DataSourceError(f"csv: no candles in {self.path}")
        return self._cache

    def fetch(self, symbol, timeframe, start_ms=None, end_ms=None, limit=None):
        candles = self._load()
        if start_ms:
            candles = [c for c in candles if c.ts >= start_ms]
        if end_ms:
            candles = [c for c in candles if c.ts <= end_ms]
        if limit:
            candles = candles[-limit:]
        return list(candles)

    def last_price(self, symbol: str) -> float:
        return self._load()[-1].close


class SyntheticSource(DataSource):
    """Deterministic geometric-Brownian-style series with regime shifts.

    Used for tests and offline demos. Same seed -> same series, always.
    """

    name = "synthetic"
    supported_timeframes = tuple(tf for tf in ("1m", "5m", "15m", "1h", "4h", "6h", "1d"))

    def __init__(self, seed: int = 7, start_price: float = 100.0, n: int = 1500,
                 timeframe: str = "1d", start_ms: int = 1_500_000_000_000):
        self.seed = seed
        self.start_price = start_price
        self.n = n
        self.timeframe = timeframe
        self.start_ms = start_ms
        self._cache: list[Candle] | None = None

    def _generate(self) -> list[Candle]:
        rng = random.Random(self.seed)
        step_ms = tf_seconds(self.timeframe) * 1000
        price = self.start_price
        out: list[Candle] = []
        drift, vol = 0.0004, 0.02
        for i in range(self.n):
            if i % 250 == 0:  # regime shift every ~250 bars
                drift = rng.choice([-0.002, -0.0005, 0.0005, 0.002, 0.003])
                vol = rng.choice([0.01, 0.02, 0.035])
            ret = drift + vol * rng.gauss(0, 1)
            o = price
            c = max(0.01, o * math.exp(ret))
            hi = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
            lo = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
            out.append(Candle(ts=self.start_ms + i * step_ms, open=o, high=hi,
                              low=max(0.005, lo), close=c,
                              volume=abs(rng.gauss(1000, 300))))
            price = c
        return out

    def _load(self) -> list[Candle]:
        if self._cache is None:
            self._cache = self._generate()
        return self._cache

    def fetch(self, symbol, timeframe, start_ms=None, end_ms=None, limit=None):
        candles = self._load()
        if start_ms:
            candles = [c for c in candles if c.ts >= start_ms]
        if end_ms:
            candles = [c for c in candles if c.ts <= end_ms]
        if limit:
            candles = candles[-limit:]
        return list(candles)

    def last_price(self, symbol: str) -> float:
        return self._load()[-1].close


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------

class AutoSource(DataSource):
    """Tries public sources in order, falling back on failure."""

    name = "auto"

    def __init__(self, timeframe: str):
        self.chain: list[DataSource] = [
            s for s in (CoinbaseSource(), KrakenSource()) if s.supports(timeframe)
        ]
        if not self.chain:
            raise DataSourceError(f"no public source supports timeframe {timeframe}")
        self.supported_timeframes = (timeframe,)

    def _try(self, fn_name: str, *args, **kwargs):
        errors = []
        for src in self.chain:
            try:
                return getattr(src, fn_name)(*args, **kwargs)
            except DataSourceError as e:
                errors.append(f"{src.name}: {e}")
        raise DataSourceError("all sources failed: " + " | ".join(errors))

    def fetch(self, symbol, timeframe, start_ms=None, end_ms=None, limit=None):
        return self._try("fetch", symbol, timeframe, start_ms=start_ms, end_ms=end_ms, limit=limit)

    def last_price(self, symbol: str) -> float:
        return self._try("last_price", symbol)


def make_source(name: str, timeframe: str, csv_path: str | None = None,
                synthetic_seed: int = 7) -> DataSource:
    name = (name or "auto").lower()
    if name == "auto":
        return AutoSource(timeframe)
    if name == "coinbase":
        return CoinbaseSource()
    if name == "kraken":
        return KrakenSource()
    if name == "csv":
        if not csv_path:
            raise DataSourceError("source 'csv' requires csv_path in the config")
        return CSVSource(csv_path)
    if name == "synthetic":
        return SyntheticSource(seed=synthetic_seed, timeframe=timeframe)
    raise DataSourceError(f"unknown data source {name!r}")
