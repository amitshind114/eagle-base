"""Paper Trading Executor — Priority 7.

Simulates buy/sell orders locally with live prices.
Tracks paper positions, PnL, and order history.

TODO (Phase 4 - Priority 7):
- Implement place_order() simulation
- Track paper positions in memory
- Calculate unrealized/realized PnL
- Integrate with RiskManager
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.base import BaseExecutor
from core.logger import logger


@dataclass
class PaperOrder:
    """Represents a simulated paper order."""

    order_id: str
    symbol: str
    side: str  # BUY or SELL
    qty: int
    price: float
    status: str = "PENDING"  # PENDING, FILLED, CANCELLED
    fill_price: float = 0.0


class PaperExecutor(BaseExecutor):
    """Simulates order execution for paper trading."""

    def __init__(self):
        self._orders: list[PaperOrder] = []
        self._positions: dict[str, dict[str, Any]] = {}

    def place_order(self, symbol: str, side: str, qty: int, price: float) -> dict[str, Any]:
        """Simulate order placement. TODO: Phase 4 Priority 7."""
        logger.info(f"Paper order: {side} {qty} {symbol} @ {price}")
        raise NotImplementedError("TODO: Phase 4 Priority 7")

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a paper order. TODO: Phase 4 Priority 7."""
        raise NotImplementedError("TODO: Phase 4 Priority 7")

    def get_positions(self) -> list[dict[str, Any]]:
        """Return current paper positions. TODO: Phase 4 Priority 7."""
        raise NotImplementedError("TODO: Phase 4 Priority 7")
