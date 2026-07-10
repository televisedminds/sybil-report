"""Broker interface implemented by the paper and live executors."""

from __future__ import annotations

from autopilot.engine.portfolio import Fill, Portfolio
from autopilot.execution.orders import OpenOrder, Order


class BrokerError(Exception):
    pass


class Broker:
    """Executes orders and tracks resting limits. Owns a Portfolio mirror."""

    portfolio: Portfolio

    def execute_market(self, order: Order, ref_price: float, ts: int) -> Fill | None:
        raise NotImplementedError

    def place_limit(self, order: Order, ts: int) -> OpenOrder | None:
        raise NotImplementedError

    def cancel(self, tag_prefix: str = "") -> int:
        """Cancel resting orders whose tag starts with tag_prefix ('' = all)."""
        raise NotImplementedError

    def open_orders(self) -> list[OpenOrder]:
        raise NotImplementedError

    def check_limit_fills(self, last_price: float, ts: int) -> list[Fill]:
        """Fill any resting limits crossed by last_price. Returns new fills."""
        raise NotImplementedError

    def sync(self) -> None:
        """Reconcile local accounting with the venue (no-op for paper)."""
