# Research: choosing and validating the income method

*Written 2026-07-10. All backtest numbers in this document were produced by
this repository's own engine on real Coinbase daily candles, with 25 bps fee
and 5 bps slippage per fill and $10,000 starting cash. Reproduce any table
with a single `autopilot backtest` command.*

## 1. The brief

"Fully automated passive income" decomposes into three requirements:

1. **The operating loop must be software end-to-end** — no content production,
   no customer support, no platform review queues, no manual fulfillment.
2. **It must run unattended** — survive crashes, restart safely, alert a human
   only when something needs a human.
3. **It must be honest** — measurable expectations, not marketing. Anything
   promising risk-free automated profit is a scam by construction: profit
   above the risk-free rate is always payment for bearing risk, providing a
   service someone pays for, or holding an edge someone else lacks.

## 2. The idea shortlist and why each won or lost

| # | Idea | Automation ceiling | Verdict |
|---|---|---|---|
| 1 | **Systematic trading of liquid crypto markets** | ~100% — data → decision → execution → accounting all API-driven, keyless simulation possible | **CHOSEN** — the only candidate where the *entire* loop is software today, testable without capital, and scalable from $0 (paper) to real money under explicit risk control |
| 2 | DeFi yield (stablecoin lending, LP provision) | ~90% | Runner-up. Real yields exist (money-market lending, LP fees), but tail risks are severe and opaque (contract exploits, depegs, impermanent loss), and safe automation requires custody engineering beyond this scope. Good future extension |
| 3 | Programmatic SEO / affiliate content sites | ~60% | Rejected: revenue gated on ad/affiliate account approvals and search-engine policy; months to first dollar; content farms are actively demoted. "Passive" is the marketing, not the reality |
| 4 | Micro-SaaS / API products | ~50% | Build once ≠ sell itself: distribution is a human grind; support is unbounded. Great business, not *passive* income |
| 5 | Digital products / print-on-demand | ~40% | Platform accounts + marketing dependency; race-to-the-bottom pricing |
| 6 | YouTube/TikTok automation channels | ~50% | Platform review risk, monetization thresholds, and quality bars; account bans are common for automated content |
| 7 | Airdrop farming / sybil operations | ~80% | **Rejected on principle and practicality**: violates protocols' terms, and — as this very repository's history shows — protocols now fund bounty hunters to confiscate sybil allocations. The 2024 LayerZero program that this repo documented is over; the durable lesson is that adversarial "free money" channels get closed and clawed back |
| 8 | P2P lending | ~70% | Jurisdiction-dependent platforms, KYC walls, illiquid defaults; can't be validated without capital |
| 9 | Domain / NFT speculation | ~30% | Illiquid, hit-driven, no testable edge |
| 10 | Running validators / staking-as-a-service | ~85% | Legitimate but yields ≈ protocol inflation minus costs; needs stake capital up front; slashing risk. Reasonable adjunct once capital exists |

Decision: **#1**, designed so #2 and #10 could later plug into the same
risk/accounting/dashboard chassis.

## 3. Method: what makes the engine trustworthy

The engine is only useful if its simulations don't flatter you. Design rules:

- **No lookahead.** Strategies see closed candles only; market orders fill at
  the *next* candle's open, worsened by slippage. Limit fills require price to
  actually trade through the level; gaps fill at the open, never better.
- **Costs always on.** 25 bps taker fee + 5 bps slippage per fill by default —
  deliberately on the expensive side of retail reality. Fee sensitivity is a
  first-class result (see §5).
- **Benchmark always shown.** Every result is printed next to buy & hold on
  the same window. A strategy that loses to holding while taking similar risk
  is a failure even if its absolute return is positive.
- **No parameter optimization.** Every default below is the canonical
  literature value (50/200 SMA, 14-period RSI, weekly DCA). Optimizing
  parameters on the same data you report is how backtests lie; we didn't.
- **Same fill code paper and simulated.** The paper broker and the backtester
  share one clipping/fee/dust implementation, so paper results validate the
  backtest assumptions rather than a second codebase.

## 4. The strategies: thesis, evidence, failure modes

### 4.1 `dca` — dollar-cost averaging with a trend filter
**Thesis:** in an asset with positive long-run drift, buying a fixed dollar
amount on a schedule harvests that drift without timing risk; a 200-day SMA
filter avoids averaging into collapses.
**Fails when:** the asset's long-run drift is over, or the budget exhausts at
the top of a cycle. Never sells by default → full market drawdowns.

### 4.2 `sma_cross` — 50/200 trend following
**Thesis:** crypto trends persist; being long only while the 50-day SMA is
above the 200-day captures the up-legs and steps aside in bear markets.
**Fails when:** sideways chop whipsaws entries/exits (each round trip costs
~0.6% in fees+slippage), or a crash is too fast for a 50-day average to react.

### 4.3 `rsi_revert` — oversold mean reversion
**Thesis:** panic dips in ranging markets bounce; buy RSI < 30, exit on recovery.
**Fails when:** "oversold" keeps falling — a downtrend is a sequence of
oversold readings. Included partly as an honest negative result (see below);
use its `trend_sma` param if you use it at all.

### 4.4 `grid` — range harvesting
**Thesis:** a ladder of resting limit orders monetizes oscillation inside a
band — the strategy every commercial "trading bot" service sells.
**Fails when:** the market trends. A rally leaves you in cash below it; a
crash leaves you fully invested above it. Included with a recentering rule so
the failure is realized and visible rather than hidden.

## 5. Evidence (real data, reproduced by one command each)

**BTC-USD daily, 2016-01-01 → 2026-07-10** — 3,844 candles; buy & hold
+14,674% with 83.8% max drawdown:

| strategy | return | CAGR | Sharpe | Sortino | max DD | exposure | fills | fees |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dca | +7,202.6% | 50.3% | 0.95 | 1.26 | 83.8% | 95% | 50 | $25 |
| sma_cross | +6,088.9% | 48.0% | 1.01 | 1.04 | 69.8% | 57% | 74 | $15,365 |
| rsi_revert | +111.7% | 7.4% | 0.51 | 0.37 | 31.1% | 20% | 45 | $1,062 |
| grid | +1,895.4% | 32.9% | 0.94 | 1.08 | 71.2% | 92% | 1,674 | $3,469 |

**BTC-USD daily, 2022-01-01 → 2026-07-10** — the harder recent regime;
buy & hold +34.8% with 67.0% max drawdown:

| strategy | return | CAGR | Sharpe | max DD |
|---|---:|---:|---:|---:|
| dca | +114.7% | 18.4% | 0.64 | 53.1% |
| sma_cross | +79.1% | 13.7% | 0.56 | 36.2% |
| rsi_revert | +9.2% | 2.0% | 0.21 | 20.8% |
| grid | **−5.2%** | −1.2% | 0.16 | 57.3% |

**ETH-USD daily, 2017-01-01 → 2026-07-10** — buy & hold +21,863% but with a
94.0% max drawdown (an entry-timing lottery):

| strategy | return | CAGR | Sharpe | max DD |
|---|---:|---:|---:|---:|
| dca | +424.4% | 19.0% | 0.61 | 87.6% |
| sma_cross | +1,293.4% | 31.9% | 0.76 | 85.6% |
| rsi_revert | **−34.3%** | −4.3% | −0.14 | 47.8% |
| grid | +1,506.0% | 33.8% | 0.78 | 89.2% |

### Intraday reality check (added 2026-07-11)

Tested on real Coinbase intraday candles: 17,766 hourly candles
(2024-07 → 2026-07, a flat window: buy & hold +2.0%) and 36,015
fifteen-minute candles (2025-07 → 2026-07, a bear window: buy & hold −40.3%).
Retail costs 25 bps fee + 5 bps slippage unless noted.

**1h, 2 years:**

| strategy | return | fills | fees | note |
|---|---:|---:|---:|---|
| dca | +1.0% | 50 | $25 | matched the flat market |
| sma_cross 50/200 | −15.6% | 126 | $2,985 | whipsawed |
| sma_cross 20/100 (faster) | **−41.2%** | 246 | $5,809 | trading faster doubled the damage |
| rsi_revert | −31.4% | 238 | $2,494 | oversold kept falling |
| grid | **+22.8%** | 215 | $441 | the chop harvester in its ideal habitat |

**15m, 1 year (bear):** everything lost — sma_cross −58.4%, rsi_revert
−53.0%, grid −26.0% (vs −40.3% for holding). At maker-tier costs
(10 bps + 2 bps) grid improved only marginally (15m: −25.4%; 1h: +25.1%).

What this measures, plainly:

1. **Speed multiplies cost, not edge.** Every faster variant did worse than
   its slower sibling, in close proportion to fees paid. Retail day trading
   competes against market-making firms with colocated servers and ~0 fees —
   it is the most crowded arena in finance, not a blue ocean.
2. **The one intraday survivor** (hourly grid) earned ≈ 11% CAGR ≈ 0.9%/month
   in a *favorable* regime — and the same strategy lost 26% in a trending
   year. Regime risk is the price of grid's steady wins.
3. The intraday config we ship (`configs/paper-daytrade-btc.json`) is that
   hourly grid with tight brakes (3% daily halt, 15% kill switch) so its bad
   regime is survivable. Expectation-setting: single-digit percent per month
   in chop, capped losses in trends, no guarantees anywhere.

### What a professional reads out of this

1. **Buy & hold won the decade on raw return.** Any honest system built on a
   147× asset admits this. The value systematic strategies added was
   *risk-shaping*: sma_cross delivered comparable CAGR with a materially
   shallower worst case (70% vs 84% on BTC), and in 2022→2026 it beat holding
   outright (+79% vs +35%) with half the drawdown.
2. **The popular "passive bot" loses in trends.** Grid — the most-sold retail
   bot strategy — was *negative* over the last 4.5 years of BTC while charging
   itself $460 in fees. On choppy high-vol ETH it did well. Grid is a bet
   that the market goes nowhere; sell that bet knowingly or not at all.
3. **Mean reversion without a trend filter is a donation.** rsi_revert lost
   34% on ETH over nine years. Kept in the platform as a documented negative
   result and as raw material (its `trend_sma` filter turns it usable).
4. **Fees are a strategy parameter.** sma_cross paid $15k in fees on BTC's
   decade (fee-free it compounds far higher). At maker-fee tiers (~10 bps)
   results improve materially — worth optimizing execution before strategy.
5. **Every max drawdown above is deeper than most humans can sit through.**
   The risk engine's caps and kill switch exist because the strategy that
   works on paper fails in production when its operator panics. Size
   positions so the historical drawdown is boring.

## 6. Overfitting and what was deliberately not done

- No grid searches, no walk-forward optimization, no per-asset tuning — the
  parameters are decades-old conventions. This costs performance and buys
  credibility; the numbers above are closer to what defaults actually deliver.
- Ten years of one asset class in one secular bull market is a *thin* sample.
  The 2022 sub-period is the closest available out-of-regime check, which is
  why it is reported.
- If you tune parameters: tune on one window, report on another, and expect
  the reported window to be worse. The `--json` output exists to script that.

## 7. Recommended operating posture

- **Default:** `sma_cross` on BTC-USD daily (configs/paper-sma-btc.json) —
  fewest decisions, clearest risk story. Or `dca` with the trend filter if you
  want accumulation semantics rather than timing.
- **Paper first, always:** 2–4 weeks minimum, compared against the backtest
  over the same dates (`autopilot report`).
- **Sizing:** only capital whose 70% drawdown you can genuinely ignore.
  `live.capital_cap` enforces the number you choose.
- **Expectation setting:** at historical Sharpe ≈ 1, a *good* year is roughly
  +vol% and a bad year is roughly −vol/2%; with these strategies' ~40–65%
  volatility that means swings most people should take at 5–20% of the
  portfolio, not 100%.
