"""SQLite persistence for paper/live sessions.

One file per session. Crash-safe (WAL); a killed process resumes exactly
where it stopped. The dashboard reads the same file from its own read-only
connection.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

from autopilot.data.candles import Candle
from autopilot.engine.portfolio import Fill

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
  symbol TEXT NOT NULL, timeframe TEXT NOT NULL, ts INTEGER NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (symbol, timeframe, ts)
);
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, side TEXT NOT NULL, qty REAL NOT NULL,
  price REAL NOT NULL, fee REAL NOT NULL, tag TEXT DEFAULT '',
  realized_pnl REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS equity (
  ts INTEGER PRIMARY KEY, equity REAL NOT NULL,
  cash REAL, qty REAL, price REAL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, level TEXT NOT NULL, kind TEXT NOT NULL, message TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class StateStore:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)

    def close(self):
        with self._lock:
            self._conn.close()

    # -- candles ------------------------------------------------------------

    def upsert_candles(self, symbol: str, timeframe: str, candles: list[Candle]) -> int:
        rows = [(symbol, timeframe, c.ts, c.open, c.high, c.low, c.close, c.volume)
                for c in candles]
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def load_candles(self, symbol: str, timeframe: str, limit: int | None = None,
                     since_ts: int | None = None) -> list[Candle]:
        q = "SELECT ts,open,high,low,close,volume FROM candles WHERE symbol=? AND timeframe=?"
        args: list = [symbol, timeframe]
        if since_ts is not None:
            q += " AND ts >= ?"
            args.append(since_ts)
        q += " ORDER BY ts DESC"
        if limit:
            q += " LIMIT ?"
            args.append(limit)
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [Candle(ts=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                for r in reversed(rows)]

    # -- fills / equity / events ---------------------------------------------

    def add_fill(self, fill: Fill) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO fills (ts,side,qty,price,fee,tag,realized_pnl) VALUES (?,?,?,?,?,?,?)",
                (fill.ts, fill.side, fill.qty, fill.price, fill.fee, fill.tag,
                 fill.realized_pnl))

    def load_fills(self, limit: int | None = None) -> list[Fill]:
        q = "SELECT ts,side,qty,price,fee,tag,realized_pnl FROM fills ORDER BY id DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        with self._lock:
            rows = self._conn.execute(q).fetchall()
        return [Fill(ts=r[0], side=r[1], qty=r[2], price=r[3], fee=r[4], tag=r[5],
                     realized_pnl=r[6]) for r in reversed(rows)]

    def add_equity(self, ts: int, equity: float, cash: float, qty: float, price: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO equity VALUES (?,?,?,?,?)",
                (ts, equity, cash, qty, price))

    def load_equity(self, limit: int | None = None) -> list[tuple[int, float]]:
        q = "SELECT ts, equity FROM equity ORDER BY ts DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        with self._lock:
            rows = self._conn.execute(q).fetchall()
        return [(r[0], r[1]) for r in reversed(rows)]

    def load_equity_full(self, limit: int | None = None) -> list[list]:
        """[ts, equity, cash, qty, price] rows, ascending."""
        q = "SELECT ts, equity, cash, qty, price FROM equity ORDER BY ts DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        with self._lock:
            rows = self._conn.execute(q).fetchall()
        return [list(r) for r in reversed(rows)]

    def add_event(self, kind: str, message: str, level: str = "info",
                  ts: int | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events (ts,level,kind,message) VALUES (?,?,?,?)",
                (ts or int(time.time() * 1000), level, kind, message))

    def load_events(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts,level,kind,message FROM events ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [{"ts": r[0], "level": r[1], "kind": r[2], "message": r[3]}
                for r in rows]

    # -- key/value (JSON) ----------------------------------------------------

    def kv_set(self, key: str, value) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                               (key, json.dumps(value)))

    def kv_get(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return default
