# Architecture

Pure Python 3.11+ standard library. One optional dependency (`ccxt`) for live
trading only. Everything else — HTTP, SQLite, the web dashboard, charts — is
stdlib or hand-rolled, so the platform runs unmodified on any box with Python.

## Data flow

```
                 ┌────────────────────────────────────────────────┐
                 │                 TradingLoop                    │
                 │  poll → new closed candle? → strategy.on_candle│
                 └──┬───────────────┬───────────────┬────────────┘
     fetch/last_price│               │actions        │equity marks
┌────────────────────▼──┐   ┌───────▼────────┐  ┌───▼─────────────┐
│ DataSource            │   │ RiskEngine     │  │ RiskEngine      │
│ coinbase → kraken     │   │ filter_order() │  │ on_equity()     │
│ (csv / synthetic)     │   │ caps & budgets │  │ halt / KILL     │
└───────────────────────┘   └───────┬────────┘  └───┬─────────────┘
                                    │allowed        │flatten on kill
                            ┌───────▼───────────────▼──┐
                            │ Broker                   │
                            │  PaperBroker (simulated) │
                            │  LiveBroker (ccxt, gated)│
                            └───────────┬──────────────┘
                                        │fills, orders
                            ┌───────────▼──────────────┐
                            │ StateStore (SQLite, WAL) │
                            │ candles·fills·equity·    │
                            │ events·kv                │
                            └───────────┬──────────────┘
                                        │read-only
                            ┌───────────▼──────────────┐
                            │ DashboardServer (http)   │
                            │ + HTML report generator  │
                            └──────────────────────────┘
```

The backtester (`engine/backtest.py`) drives the same `Strategy` interface
over historical candles with the same fill helper as the paper broker, so
simulation, paper and live share one behavioral contract.

## Module map

| Path | Responsibility |
|---|---|
| `autopilot/config.py` | JSON config → validated dataclasses; unknown keys rejected |
| `autopilot/data/candles.py` | Candle type, timeframes, CSV codec, UTC helpers |
| `autopilot/data/sources.py` | Coinbase/Kraken public APIs (pagination, retries, fallback), CSV, deterministic synthetic |
| `autopilot/strategies/` | `Strategy` base + `dca`, `sma_cross`, `rsi_revert`, `grid`; `indicators.py` |
| `autopilot/engine/portfolio.py` | Cash/position accounting, avg-cost realized PnL, shared clipped-fill rules |
| `autopilot/engine/backtest.py` | Event-driven simulator (signals on close, fills next open, limit semantics) |
| `autopilot/engine/metrics.py` | CAGR, Sharpe/Sortino, drawdown, exposure, win rate, benchmark comparison |
| `autopilot/execution/orders.py` | Order/Cancel intents, target-position sizing with rebalance band |
| `autopilot/execution/risk.py` | Order caps, daily-loss halt, max-drawdown kill switch (persistable) |
| `autopilot/execution/paper.py` | Simulated broker over live prices, persistent |
| `autopilot/execution/live_ccxt.py` | Real orders via ccxt; four interlocks; hard capital ceiling |
| `autopilot/runner/loop.py` | The 24/7 daemon: crash-only design, catch-up limits, heartbeats |
| `autopilot/runner/state.py` | SQLite store (WAL) for candles/fills/equity/events/kv |
| `autopilot/runner/notify.py` | Webhook notifications (Discord/Slack-shaped JSON) |
| `autopilot/server/page.py` | Shared design tokens + dependency-free SVG line chart (tooltips, dark mode) |
| `autopilot/server/dashboard.py` | Read-only local web UI over a session db |
| `autopilot/server/report.py` | Self-contained HTML backtest/session reports |
| `autopilot/cli.py` | `init fetch backtest demo paper live dashboard status resume report` |

## Design decisions worth knowing

- **Crash-only loop.** Every step persists before sleeping; `kill -9` at any
  point loses nothing. On restart after downtime the loop refuses to act on
  more than 3 stale candles (`CATCHUP_LIMIT`) — trading last week's signals
  at today's price is worse than skipping them.
- **Fresh sessions do not replay history.** Bootstrap marks the latest closed
  candle as processed; trading starts with the next one.
- **Strategies are pure deciders.** They see candles + their own persisted
  `state` dict and return intents. No strategy touches cash, HTTP, or the
  database — that's what makes backtests honest and tests easy.
- **Risk is a separate layer.** Strategies cannot bypass `filter_order`, and
  the kill switch acts even if a strategy misbehaves (`max_orders_per_day`
  bounds runaway loops).
- **Sells are never size-blocked.** Risk caps constrain increasing exposure;
  reducing it is always allowed.
- **The live capital cap is structural.** The live broker's internal cash
  mirror is seeded with `min(exchange_balance, capital_cap)` and buys are
  clipped against it — the ceiling holds even if the exchange account is 10×
  larger.
- **One symbol per process.** Multi-asset portfolios multiply failure modes;
  run N processes with N configs/state files instead.

## Adding a strategy (~30 lines)

```python
# autopilot/strategies/breakout.py
from autopilot.execution.orders import target_position_order
from autopilot.strategies.base import Ctx, Strategy, StrategyError

class BreakoutStrategy(Strategy):
    name = "breakout"
    defaults = {"lookback": 55, "target_frac": 0.9}

    def validate(self):
        if self.p["lookback"] < 2:
            raise StrategyError("breakout: lookback must be >= 2")
        self.warmup = int(self.p["lookback"]) + 1

    def on_candle(self, ctx: Ctx):
        highs = [c.high for c in ctx.candles[-self.p["lookback"] - 1:-1]]
        frac = self.p["target_frac"] if ctx.price > max(highs) else 0.0
        order = target_position_order(ctx.equity, ctx.price, ctx.qty, frac)
        return [order] if order else []
```

Register it in `strategies/__init__.py`, add a test in
`tests/test_strategies.py`, and every surface — backtest, paper, live,
dashboard, reports — picks it up by name.

## Testing

`python3 -m unittest discover -s tests` — 93 tests, fully offline
(exchange APIs are fixture-mocked; the loop runs on a fake clock; live
broker tests use a stub exchange). CI (`.github/workflows/tests.yml`) runs
the suite plus an end-to-end offline demo on 3.11 and 3.12.
