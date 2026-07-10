# Autopilot — a self-hosted systematic trading platform

Autopilot is a complete, zero-dependency Python platform that runs rule-based
trading strategies 24/7: it fetches market data, decides, executes, enforces
risk limits, persists every event, and serves a live web dashboard — with no
accounts, no API keys, and no money required to start. It paper-trades real
market prices out of the box; putting real money behind it is a separate,
deliberately hard-to-flip switch.

**The honest part, first.** There is no machine that guarantees profit — anyone
selling one is lying to you. What professionals actually run is *systematic
trading infrastructure*: strategies with a understood edge and failure modes,
validated on history, executed with strict risk control, and monitored. That is
what this is. It automates 100% of the *operation*. It cannot automate away
*risk*. Backtests here are measurements of the past, not promises about the
future. Read [docs/RISKS.md](docs/RISKS.md) before even thinking about live mode.

*(This repository previously hosted the LayerZero sybil-report bounty docs —
that program ended in 2024; the original README is preserved at
[docs/legacy/LAYERZERO-SYBIL-REPORTING.md](docs/legacy/LAYERZERO-SYBIL-REPORTING.md).)*

## 60-second start

Requires only Python 3.11+. No pip installs, no keys, no accounts.
**New to this? Follow the step-by-step [docs/QUICKSTART.md](docs/QUICKSTART.md).**

```bash
# 1) Offline demo: backtest all 4 strategies on 10 years of bundled BTC data
python3 -m autopilot demo            # prints metrics, writes reports/demo-report.html

# 2) Answer five questions, get a ready-to-run config
python3 -m autopilot init

# 3) Paper-trade live prices (public data, fake money), with a dashboard
python3 -m autopilot paper --config configs/sma_cross-btc-usd-paper.json
# → dashboard at http://127.0.0.1:8899  · Ctrl-C stops; state persists; restart resumes
```

That second command is the actual product: a daemon that trades a simulated
account against live market data around the clock, so a strategy can prove
itself for weeks before a single real dollar is exposed.

## What's inside

| Piece | What it does |
|---|---|
| **Backtester** | Event-driven, no lookahead (signals on close, fills next open), fees + slippage modeled, honest metrics vs buy & hold |
| **4 strategies** | `dca` (accumulation w/ trend filter) · `sma_cross` (trend following) · `rsi_revert` (mean reversion) · `grid` (range harvesting) — all parameterized, all documented with failure modes |
| **Risk engine** | Per-order & position caps → daily-loss halt → max-drawdown **kill switch** that flattens and stays down until a human runs `autopilot resume` |
| **Paper broker** | Live public prices (Coinbase → Kraken fallback), simulated fills with slippage/fees, crash-safe SQLite state |
| **Live broker** | Real orders via [ccxt](https://github.com/ccxt/ccxt) (optional install), gated behind [four interlocks](docs/GO-LIVE.md), hard capital ceiling the bot cannot exceed |
| **Dashboard** | Local web UI: equity vs buy & hold, positions, trades, events, risk state. Read-only, zero JS dependencies |
| **Reports** | One-file HTML backtest/session reports you can archive or share |

Everything is Python standard library. `ccxt` is needed only for live trading.

## Commands

```bash
python3 -m autopilot init                            # interactive setup wizard
python3 -m autopilot demo                            # offline demo + report
python3 -m autopilot fetch     --symbol ETH-USD --timeframe 1d --start 2020-01-01 --out data.csv
python3 -m autopilot backtest  --csv data.csv --strategies dca,sma_cross,rsi_revert,grid --report r.html
python3 -m autopilot backtest  --config configs/backtest-btc.json
python3 -m autopilot paper     --config configs/paper-dca-btc.json
python3 -m autopilot status    --state state/paper-dca-btc.db
python3 -m autopilot report    --state state/paper-dca-btc.db --out session.html
python3 -m autopilot dashboard --state state/paper-dca-btc.db --port 8899
python3 -m autopilot resume    --state state/paper-dca-btc.db   # re-arm after kill switch
python3 -m autopilot live      --config configs/live-template.json   # REAL MONEY — read docs/GO-LIVE.md
```

Run several markets/strategies at once by launching multiple `paper` processes,
each with its own config and `state_db`.

## What the data actually says

Full-period backtests on real Coinbase daily candles (25 bps fee + 5 bps
slippage per fill, $10,000 start). Generated with `autopilot backtest`;
regenerate any time — numbers below were produced 2026-07-10:

**BTC-USD 2016 → 2026** (buy & hold: +14,674%, but with an 84% max drawdown)

| strategy | return | CAGR | Sharpe | max DD | fills |
|---|---:|---:|---:|---:|---:|
| dca (trend-filtered) | +7,203% | 50.3% | 0.95 | 83.8% | 50 |
| sma_cross 50/200 | +6,089% | 48.0% | 1.01 | 69.8% | 74 |
| rsi_revert | +112% | 7.4% | 0.51 | 31.1% | 45 |
| grid | +1,895% | 32.9% | 0.94 | 71.2% | 1,674 |

**BTC-USD 2022 → 2026** (harder regime; buy & hold: +34.8%, max DD 67%)

| strategy | return | CAGR | Sharpe | max DD |
|---|---:|---:|---:|---:|
| dca (trend-filtered) | +114.7% | 18.4% | 0.64 | 53.1% |
| sma_cross 50/200 | +79.1% | 13.7% | 0.56 | 36.2% |
| rsi_revert | +9.2% | 2.0% | 0.21 | 20.8% |
| grid | **−5.2%** | −1.2% | 0.16 | 57.3% |

Read those tables the way a professional would: nothing beat buy & hold's raw
return over a decade in which BTC went up ~147× — but trend-following matched
its growth with a third less drawdown and *beat it outright* in the recent
regime, while grid (the strategy every "passive income bot" service sells)
**lost money** in a trending market. Full analysis, per-strategy failure modes,
and why these four strategies were chosen: [docs/RESEARCH.md](docs/RESEARCH.md).

## The path to real money (if you choose it)

1. Run `paper` for **2–4 weeks minimum**; compare results to the backtest.
2. Read [docs/GO-LIVE.md](docs/GO-LIVE.md) and [docs/RISKS.md](docs/RISKS.md) fully.
3. Create an exchange API key with **trade-only** permission (no withdrawals).
4. `pip install ccxt`, set the three environment interlocks, set a small
   `capital_cap` you can lose without pain.
5. `python3 -m autopilot live --config your-live.json` — the risk engine,
   kill switch, and dashboard behave exactly as they did on paper.

The bot never touches more cash than `live.capital_cap`, halts itself for the
day after the daily-loss limit, and flattens + locks after the max-drawdown
limit until you personally re-arm it.

## Development

```bash
python3 -m unittest discover -s tests    # 93 tests, all offline
```

Architecture and extension guide (adding a strategy is ~30 lines):
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). CI runs the suite plus an
offline end-to-end demo on every push.

## Disclaimer

This software is provided for education and research. It is not investment
advice. Crypto assets are extremely volatile; leverage of any kind is not
supported on purpose. You are solely responsible for anything you deploy with
real funds, including tax obligations. Past performance — simulated or real —
does not indicate future results.
