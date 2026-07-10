"""Event-driven backtester.

Execution model (deliberately conservative, no lookahead):
  * Strategies decide on a candle's CLOSE.
  * Market orders fill at the NEXT candle's open, worsened by slippage_bps.
  * Limit orders rest from the next candle onward and fill when price
    trades through them (buy: low <= limit, sell: high >= limit); a gap
    through the level fills at the open (favorable), otherwise at the limit.
  * Taker/maker fees are charged on every fill (fee_bps).
  * Buys are clipped to available cash, sells to the held quantity, and
    anything below MIN_TRADE_QUOTE notional is skipped as dust.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from autopilot.data.candles import Candle
from autopilot.engine.metrics import Metrics, compute_metrics
from autopilot.engine.portfolio import Fill, Portfolio, apply_clipped_fill
from autopilot.execution.orders import BUY, MARKET, Cancel, OpenOrder, Order
from autopilot.strategies.base import Ctx, Strategy


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    strategy: str
    params: dict
    start_cash: float
    fee_bps: float
    slippage_bps: float
    metrics: Metrics
    equity_curve: list[tuple[int, float]]
    fills: list[Fill]
    closes: list[tuple[int, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "params": self.params,
            "start_cash": self.start_cash,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "metrics": self.metrics.to_dict(),
            "equity_curve": [[ts, round(eq, 2)] for ts, eq in self.equity_curve],
            "fills": [
                {"ts": f.ts, "side": f.side, "qty": f.qty, "price": f.price,
                 "fee": round(f.fee, 4), "tag": f.tag,
                 "realized_pnl": round(f.realized_pnl, 2)}
                for f in self.fills
            ],
            "closes": [[ts, px] for ts, px in self.closes],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class Backtester:
    def __init__(self, candles: list[Candle], strategy: Strategy, symbol: str = "?",
                 timeframe: str = "1d", start_cash: float = 10_000.0,
                 fee_bps: float = 25.0, slippage_bps: float = 5.0):
        if len(candles) < 2:
            raise ValueError("need at least 2 candles to backtest")
        self.candles = candles
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self.start_cash = start_cash
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def run(self) -> BacktestResult:
        pf = Portfolio(self.start_cash)
        strat = self.strategy
        state: dict = {}
        pending_market: list[Order] = []
        open_limits: list[OpenOrder] = []
        equity_curve: list[tuple[int, float]] = []
        exposure_flags: list[bool] = []
        slip = self.slippage_bps / 10_000

        for i, candle in enumerate(self.candles):
            # 1) Fill market orders queued on the previous close, at this open.
            for order in pending_market:
                px = candle.open * (1 + slip if order.side == BUY else 1 - slip)
                qty = order.resolve_qty(px)
                apply_clipped_fill(pf, order.side, qty, px, self.fee_bps, candle.ts, order.tag)
            pending_market = []

            # 2) Check resting limit orders against this candle's range.
            still_open: list[OpenOrder] = []
            for oo in open_limits:
                o = oo.order
                crossed = (candle.low <= o.limit_price if o.side == BUY
                           else candle.high >= o.limit_price)
                if not crossed:
                    still_open.append(oo)
                    continue
                if o.side == BUY:
                    px = min(candle.open, o.limit_price)
                else:
                    px = max(candle.open, o.limit_price)
                apply_clipped_fill(pf, o.side, o.base_qty, px, self.fee_bps, candle.ts, o.tag)
            open_limits = still_open

            # 3) Let the strategy react to this candle's close.
            price = candle.close
            if i + 1 >= strat.warmup:
                ctx = Ctx(candles=self.candles[: i + 1], ts=candle.ts, price=price,
                          cash=pf.cash, qty=pf.qty, avg_cost=pf.avg_cost,
                          equity=pf.equity(price), open_orders=list(open_limits),
                          state=state)
                for action in strat.on_candle(ctx) or []:
                    if isinstance(action, Cancel):
                        open_limits = [oo for oo in open_limits
                                       if action.tag and not oo.tag.startswith(action.tag)]
                    elif isinstance(action, Order):
                        if action.otype == MARKET:
                            pending_market.append(action)
                        else:
                            open_limits.append(OpenOrder(order=action, placed_ts=candle.ts))

            equity_curve.append((candle.ts, pf.equity(price)))
            exposure_flags.append(pf.qty > 0)

        closes = [c.close for c in self.candles]
        metrics = compute_metrics(equity_curve, pf.fills, self.timeframe,
                                  self.start_cash, closes, exposure_flags)
        return BacktestResult(
            symbol=self.symbol, timeframe=self.timeframe, strategy=strat.name,
            params=dict(strat.p), start_cash=self.start_cash, fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps, metrics=metrics,
            equity_curve=equity_curve, fills=pf.fills,
            closes=[(c.ts, c.close) for c in self.candles],
        )
