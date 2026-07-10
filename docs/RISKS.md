# Risks — read before live mode

This platform automates the *work* of trading. It does not, and cannot,
automate away the *risk*. This page is the plain-language version of what can
go wrong. If any of it is surprising, stay in paper mode.

## The one-paragraph version

Returns above the risk-free rate are payment for bearing risk. A strategy
with a backtested Sharpe near 1 loses money roughly one year in three. The
strategies shipped here drew down 30–85% at some point in the last decade —
simulated investors who "couldn't lose" on paper went broke in production by
quitting (or leveraging) at the bottom. Size positions so the historical
worst case is boring, and treat any promise of safe automated yield — from
anyone, including your own backtests — as the sales pitch of someone who
wants your money.

## Market risk
- Crypto majors routinely fall 50–90% peak-to-trough. Every shipped strategy
  except `rsi_revert` spent most of the decade >50% underwater at least once.
- Backtests measure one historical path. The future draws from a different
  distribution: regimes change (see grid: profitable 2016–2021 chop, negative
  2022–2026 trend).
- Correlations go to 1 in a crash: running three crypto pairs is not
  diversification.

## Model & data risk
- **Overfitting:** parameters tuned to the past encode noise. We ship
  untuned literature defaults on purpose; the moment you optimize, distrust
  your numbers (see RESEARCH.md §6).
- **Costs drift:** the 25 bps fee + 5 bps slippage model is realistic for
  small retail size today. Larger orders, thin books, or volatile moments
  fill worse than the model.
- **Data quality:** public candle feeds occasionally gap or revise. The
  engine tolerates missing polls, but a strategy decision made on a bad
  candle is still a decision.

## Execution & operational risk
- The paper broker fills at the touch; a real exchange may partially fill,
  reject, or hang. The live wrapper handles the common cases; it cannot make
  a flaky venue reliable.
- The loop is crash-safe (state resumes) but not outage-proof: while your
  machine or the exchange is down, positions remain open and unmanaged. After
  long downtime the loop deliberately skips stale signals (`catchup_skip`).
- A trade-only API key can still *trade away* your balance if leaked. Never
  grant withdrawal permission; IP-allowlist the key; keep keys in environment
  variables, never in files or shells' history.

## Platform (exchange) risk
- Exchanges get hacked, freeze withdrawals, and fail (Mt. Gox, FTX). Funds on
  an exchange are a creditor claim, not custody. Keep only working capital
  there; sweep profits out on a schedule — manually, since this bot has (by
  design) no withdrawal capability.

## Legal & tax
- Every fill is likely a taxable event in most jurisdictions; hundreds of
  fills a year is a real accounting burden (`fills` table exports cleanly).
- Whether you may run automated trading at all, and on which venues, depends
  on your jurisdiction. That's your homework, not the software's.

## What the risk engine does — and doesn't
Does: cap single-order and total position size; halt new orders for the UTC
day after `daily_loss_limit_pct`; flatten and lock the session after
`max_drawdown_pct` until a human runs `resume`; cap orders/day against
runaway loops; never touch more than `live.capital_cap`.

Doesn't: prevent losses inside those limits (a 25% drawdown limit means you
can lose 25%); protect against exchange failure, key theft, or a gap through
a level; know anything about your other holdings.

## The honest hierarchy of "passive" yield
If your actual goal is yield with minimal effort, know where each rung sits:

1. **Treasury bills / money-market funds** — the true risk-free-ish baseline.
2. **Staking major PoS assets** — protocol inflation minus slashing/custody risk.
3. **Systematic spot trading (this platform)** — risk-bearing, edge-dependent,
   effort mostly up front; returns uncertain by nature.
4. **Leverage / futures / yield farming** — faster in both directions; not
   supported here on purpose.

Anything advertising rung-4 returns with rung-1 safety is fraud.
