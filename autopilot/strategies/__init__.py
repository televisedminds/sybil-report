from autopilot.strategies.base import Ctx, Strategy, StrategyError
from autopilot.strategies.dca import DCAStrategy
from autopilot.strategies.grid import GridStrategy
from autopilot.strategies.rsi_revert import RsiRevertStrategy
from autopilot.strategies.sma_cross import SmaCrossStrategy

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls
    for cls in (DCAStrategy, SmaCrossStrategy, RsiRevertStrategy, GridStrategy)
}


def make_strategy(name: str, params: dict | None = None) -> Strategy:
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise StrategyError(
            f"unknown strategy {name!r}; available: {', '.join(sorted(REGISTRY))}"
        ) from None
    return cls(params)


__all__ = ["Ctx", "Strategy", "StrategyError", "REGISTRY", "make_strategy"]
