"""Honest performance metrics for equity curves.

Every number here is a historical measurement, not a forecast. Sharpe and
volatility are annualized assuming crypto's 365-day market year.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

from autopilot.data.candles import tf_seconds
from autopilot.engine.portfolio import Fill

SECONDS_PER_YEAR = 365 * 86400


@dataclass
class Metrics:
    start_ts: int
    end_ts: int
    bars: int
    days: float
    start_cash: float
    final_equity: float
    total_return_pct: float
    cagr_pct: float
    volatility_pct: float          # annualized stdev of per-bar returns
    sharpe: float                  # rf=0
    sortino: float
    max_drawdown_pct: float
    exposure_pct: float            # % of bars holding a position
    n_fills: int
    n_sells: int
    win_rate_pct: float            # % of sell fills with positive net realized PnL
    profit_factor: float           # gross realized gains / gross realized losses
    fees_paid: float
    benchmark_return_pct: float    # buy & hold same asset, same window
    benchmark_max_drawdown_pct: float

    def to_dict(self) -> dict:
        return asdict(self)


def max_drawdown_pct(values: list[float]) -> float:
    peak = float("-inf")
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak)
    return abs(worst) * 100


def _annualize_factor(timeframe: str) -> float:
    return SECONDS_PER_YEAR / tf_seconds(timeframe)


def _mean_std(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    mean = sum(xs) / n
    if n < 2:
        return mean, 0.0
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return mean, math.sqrt(var)


def compute_metrics(equity_curve: list[tuple[int, float]], fills: list[Fill],
                    timeframe: str, start_cash: float,
                    benchmark_closes: list[float],
                    exposure_flags: list[bool] | None = None) -> Metrics:
    if not equity_curve:
        raise ValueError("empty equity curve")
    ts0, eq0 = equity_curve[0]
    ts1, eq1 = equity_curve[-1]
    values = [e for _, e in equity_curve]
    bars = len(equity_curve)
    days = max((ts1 - ts0) / 86_400_000, 1e-9)
    years = days / 365

    total_return = (eq1 / start_cash - 1) * 100
    cagr = ((eq1 / start_cash) ** (1 / years) - 1) * 100 if years > 0.05 and eq1 > 0 else total_return

    rets = []
    for i in range(1, bars):
        prev = values[i - 1]
        rets.append(values[i] / prev - 1 if prev > 0 else 0.0)
    mean, std = _mean_std(rets)
    ann = _annualize_factor(timeframe)
    vol = std * math.sqrt(ann) * 100
    sharpe = (mean / std) * math.sqrt(ann) if std > 1e-12 else 0.0
    downside = [r for r in rets if r < 0]
    _, dstd = _mean_std(downside)
    sortino = (mean / dstd) * math.sqrt(ann) if dstd > 1e-12 else (sharpe if sharpe else 0.0)

    sells = [f for f in fills if f.side == "sell"]
    wins = [f for f in sells if f.realized_pnl > 0]
    gains = sum(f.realized_pnl for f in sells if f.realized_pnl > 0)
    losses = abs(sum(f.realized_pnl for f in sells if f.realized_pnl < 0))
    profit_factor = gains / losses if losses > 1e-9 else (math.inf if gains > 0 else 0.0)

    exposure = (
        100 * sum(1 for f in exposure_flags if f) / len(exposure_flags)
        if exposure_flags else 0.0
    )

    bench_return = 0.0
    bench_dd = 0.0
    if benchmark_closes:
        first = benchmark_closes[0]
        if first > 0:
            bench_return = (benchmark_closes[-1] / first - 1) * 100
            bench_dd = max_drawdown_pct(benchmark_closes)

    return Metrics(
        start_ts=ts0, end_ts=ts1, bars=bars, days=round(days, 1),
        start_cash=start_cash, final_equity=round(eq1, 2),
        total_return_pct=round(total_return, 2), cagr_pct=round(cagr, 2),
        volatility_pct=round(vol, 2), sharpe=round(sharpe, 2),
        sortino=round(sortino, 2),
        max_drawdown_pct=round(max_drawdown_pct(values), 2),
        exposure_pct=round(exposure, 1), n_fills=len(fills), n_sells=len(sells),
        win_rate_pct=round(100 * len(wins) / len(sells), 1) if sells else 0.0,
        profit_factor=round(profit_factor, 2) if math.isfinite(profit_factor) else float("inf"),
        fees_paid=round(sum(f.fee for f in fills), 2),
        benchmark_return_pct=round(bench_return, 2),
        benchmark_max_drawdown_pct=round(bench_dd, 2),
    )
