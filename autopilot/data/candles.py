"""Candle primitives shared by every layer of the platform.

All timestamps are integer epoch milliseconds, UTC. Candle series are lists
of Candle sorted ascending by ts with no duplicates.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone

TIMEFRAMES: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "6h": 21600,
    "1d": 86400,
}

CSV_HEADER = ["ts_ms", "open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class Candle:
    ts: int  # open time, epoch ms UTC
    open: float
    high: float
    low: float
    close: float
    volume: float


def tf_seconds(timeframe: str) -> int:
    try:
        return TIMEFRAMES[timeframe]
    except KeyError:
        raise ValueError(
            f"unknown timeframe {timeframe!r}; supported: {', '.join(TIMEFRAMES)}"
        ) from None


def is_closed(candle: Candle, timeframe: str, now_ms: int) -> bool:
    """A candle is closed once its full interval has elapsed."""
    return candle.ts + tf_seconds(timeframe) * 1000 <= now_ms


def parse_date_ms(text: str) -> int:
    """Parse 'YYYY-MM-DD' or full ISO-8601 into epoch ms (assumes UTC)."""
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"invalid date {text!r}; expected YYYY-MM-DD or ISO-8601") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fmt_ts(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def dedupe_sorted(candles: list[Candle]) -> list[Candle]:
    """Sort ascending by ts and drop duplicate timestamps (keep last seen)."""
    by_ts: dict[int, Candle] = {}
    for c in candles:
        by_ts[c.ts] = c
    return [by_ts[ts] for ts in sorted(by_ts)]


def candles_to_csv(candles: list[Candle]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    for c in candles:
        writer.writerow([c.ts, repr(c.open), repr(c.high), repr(c.low), repr(c.close), repr(c.volume)])
    return buf.getvalue()


def candles_from_csv(text: str) -> list[Candle]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    start = 1 if rows[0] and rows[0][0].strip().lower() in ("ts_ms", "ts", "timestamp") else 0
    out = []
    for row in rows[start:]:
        if not row or not row[0].strip():
            continue
        out.append(
            Candle(
                ts=int(float(row[0])),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]) if len(row) > 5 and row[5] != "" else 0.0,
            )
        )
    return dedupe_sorted(out)
