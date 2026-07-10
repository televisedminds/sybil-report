"""Strategy interface.

A strategy sees closed candles only and returns a list of actions
(Order / Cancel). It never touches cash or exchange APIs directly — the
execution layer (backtester, paper broker, live broker) applies risk checks
and turns intents into fills. Strategies must be deterministic: same candle
history + same state => same actions. That is what makes backtests honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autopilot.data.candles import Candle
from autopilot.execution.orders import Cancel, OpenOrder, Order


class StrategyError(Exception):
    pass


@dataclass
class Ctx:
    """Everything a strategy may look at when deciding."""

    candles: list[Candle]          # ascending, last item = candle that just closed
    ts: int                        # ts of the just-closed candle
    price: float                   # its close
    cash: float
    qty: float
    avg_cost: float
    equity: float
    open_orders: list[OpenOrder] = field(default_factory=list)
    state: dict = field(default_factory=dict)   # persists across candles/restarts

    @property
    def closes(self) -> list[float]:
        return [c.close for c in self.candles]


class Strategy:
    name = "base"
    defaults: dict = {}
    # Minimum number of candles required before the strategy may trade.
    warmup = 0

    def __init__(self, params: dict | None = None):
        params = dict(params or {})
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise StrategyError(
                f"{self.name}: unknown params {sorted(unknown)}; "
                f"valid: {sorted(self.defaults)}")
        self.p = {**self.defaults, **params}
        self.validate()

    def validate(self) -> None:
        """Raise StrategyError on bad parameter combinations."""

    def on_candle(self, ctx: Ctx) -> list[Order | Cancel]:
        return []

    def describe(self) -> str:
        return f"{self.name}({', '.join(f'{k}={v}' for k, v in sorted(self.p.items()))})"
