"""Configuration: one JSON file describes one trading session.

Unknown keys are rejected so typos fail loudly instead of silently running
with defaults. See configs/ for annotated examples.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from autopilot.data.candles import TIMEFRAMES

MODES = ("backtest", "paper", "live")


class ConfigError(Exception):
    pass


def _take(d: dict, section: str, allowed: dict[str, Any]) -> dict:
    d = {k: v for k, v in d.items() if not k.startswith("_")}  # _keys = comments
    unknown = set(d) - set(allowed)
    if unknown:
        raise ConfigError(f"{section}: unknown keys {sorted(unknown)}; valid: {sorted(allowed)}")
    return {**allowed, **d}


@dataclass
class RiskConfig:
    max_position_pct: float = 100.0     # position value cap, % of equity
    max_order_pct: float = 30.0         # single order cap, % of equity
    daily_loss_limit_pct: float = 5.0   # halt new orders for the UTC day
    max_drawdown_pct: float = 30.0      # kill switch: flatten + halt for good
    max_orders_per_day: int = 60        # runaway-loop guard
    flatten_on_kill: bool = True

    def validate(self):
        for name in ("max_position_pct", "max_order_pct", "daily_loss_limit_pct",
                     "max_drawdown_pct"):
            v = getattr(self, name)
            if not (0 < v <= 100):
                raise ConfigError(f"risk.{name} must be in (0, 100], got {v}")
        if self.max_orders_per_day < 1:
            raise ConfigError("risk.max_orders_per_day must be >= 1")


@dataclass
class Config:
    mode: str = "paper"
    symbol: str = "BTC-USD"
    timeframe: str = "1h"
    source: str = "auto"                # auto | coinbase | kraken | csv | synthetic
    csv_path: str | None = None
    strategy_name: str = "dca"
    strategy_params: dict = field(default_factory=dict)
    start_cash: float = 10_000.0
    fee_bps: float = 25.0               # 0.25% per fill — typical retail taker fee
    slippage_bps: float = 5.0
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest_start: str | None = None   # YYYY-MM-DD
    backtest_end: str | None = None
    poll_seconds: int = 60
    state_db: str = "state/session.db"
    dashboard_enabled: bool = True
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8899
    webhook_url: str | None = None
    live_exchange: str = "kraken"
    live_capital_cap: float = 0.0       # hard ceiling on cash the bot may use

    def validate(self):
        if self.mode not in MODES:
            raise ConfigError(f"mode must be one of {MODES}, got {self.mode!r}")
        if not self.symbol or "-" not in self.symbol.replace("/", "-"):
            raise ConfigError(f"symbol must look like 'BTC-USD', got {self.symbol!r}")
        if self.timeframe not in TIMEFRAMES:
            raise ConfigError(f"timeframe must be one of {sorted(TIMEFRAMES)}, got {self.timeframe!r}")
        if self.start_cash <= 0:
            raise ConfigError("start_cash must be positive")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ConfigError("fee_bps / slippage_bps must be >= 0")
        if self.poll_seconds < 1:
            raise ConfigError("poll_seconds must be >= 1")
        if self.source == "csv" and not self.csv_path:
            raise ConfigError("source 'csv' requires csv_path")
        if self.mode == "live" and self.live_capital_cap <= 0:
            raise ConfigError(
                "live mode requires live.capital_cap > 0 — an explicit hard ceiling "
                "on how much cash the bot may touch")
        self.risk.validate()

    @staticmethod
    def from_dict(raw: dict) -> "Config":
        top = _take(raw, "config", {
            "mode": "paper", "symbol": "BTC-USD", "timeframe": "1h", "source": "auto",
            "csv_path": None, "strategy": {}, "start_cash": 10_000.0, "fee_bps": 25.0,
            "slippage_bps": 5.0, "risk": {}, "backtest": {}, "paper": {}, "live": {},
            "dashboard": {}, "notify": {},
        })
        strat = _take(top["strategy"] or {}, "strategy", {"name": "dca", "params": {}})
        risk = RiskConfig(**_take(top["risk"] or {}, "risk", {
            "max_position_pct": 100.0, "max_order_pct": 30.0,
            "daily_loss_limit_pct": 5.0, "max_drawdown_pct": 30.0,
            "max_orders_per_day": 60, "flatten_on_kill": True}))
        bt = _take(top["backtest"] or {}, "backtest", {"start": None, "end": None})
        paper = _take(top["paper"] or {}, "paper",
                      {"poll_seconds": 60, "state_db": "state/session.db"})
        live = _take(top["live"] or {}, "live",
                     {"exchange": "kraken", "capital_cap": 0.0})
        dash = _take(top["dashboard"] or {}, "dashboard",
                     {"enabled": True, "host": "127.0.0.1", "port": 8899})
        notify = _take(top["notify"] or {}, "notify", {"webhook_url": None})

        cfg = Config(
            mode=top["mode"], symbol=top["symbol"].upper().replace("/", "-"),
            timeframe=top["timeframe"], source=top["source"], csv_path=top["csv_path"],
            strategy_name=strat["name"], strategy_params=dict(strat["params"] or {}),
            start_cash=float(top["start_cash"]), fee_bps=float(top["fee_bps"]),
            slippage_bps=float(top["slippage_bps"]), risk=risk,
            backtest_start=bt["start"], backtest_end=bt["end"],
            poll_seconds=int(paper["poll_seconds"]), state_db=paper["state_db"],
            dashboard_enabled=bool(dash["enabled"]), dashboard_host=dash["host"],
            dashboard_port=int(dash["port"]), webhook_url=notify["webhook_url"],
            live_exchange=live["exchange"], live_capital_cap=float(live["capital_cap"]),
        )
        cfg.validate()
        return cfg

    @staticmethod
    def load(path: str) -> "Config":
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except OSError as e:
            raise ConfigError(f"cannot read config {path}: {e}") from None
        except json.JSONDecodeError as e:
            raise ConfigError(f"config {path} is not valid JSON: {e}") from None
        if not isinstance(raw, dict):
            raise ConfigError(f"config {path} must be a JSON object")
        return Config.from_dict(raw)
