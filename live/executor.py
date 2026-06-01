"""Live Executor — Priority 10.

⚠️  WARNING: This module places REAL orders with REAL money.
Only enable after paper trading is fully validated.

TODO (Phase 4 - Priority 10 — LAST):
- Implement Angel One order placement
- Session management and token refresh
- Order status polling
- Emergency kill switch
"""

from __future__ import annotations

from typing import Any

from core.base import BaseExecutor
from core.logger import logger

LIVE_ENABLED = False  # ⚠️  Set to True ONLY after full paper trading validation


class LiveExecutor(BaseExecutor):
    """Live order executor via Angel One SmartAPI."""

    def __init__(self):
        if not LIVE_ENABLED:
            logger.warning("LiveExecutor: LIVE_ENABLED=False — live trading is disabled")

    def place_order(self, symbol: str, side: str, qty: int, price: float) -> dict[str, Any]:
        """Place a real order via Angel One. TODO: Phase 4 Priority 10."""
        if not LIVE_ENABLED:
            raise RuntimeError("Live trading is disabled. Set LIVE_ENABLED=True after paper validation.")
        raise NotImplementedError("TODO: Phase 4 Priority 10 — last module to implement")

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError("TODO: Phase 4 Priority 10")

    def get_positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError("TODO: Phase 4 Priority 10")
