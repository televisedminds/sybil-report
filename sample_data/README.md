# Bundled sample data

Real daily OHLCV candles from the Coinbase Exchange public API, committed so
`autopilot demo` and offline backtests work with zero network access.

| file | range | candles | fetched |
|---|---|---|---|
| `BTC-USD-1d.csv` | 2016-01-01 → 2026-07-10 | 3,844 | 2026-07-10 |
| `ETH-USD-1d.csv` | 2017-01-01 → 2026-07-10 | 3,478 | 2026-07-10 |

Format: `ts_ms,open,high,low,close,volume` (UTC, ascending).

Refresh any time:

```bash
bash scripts/refresh_sample_data.sh
```
