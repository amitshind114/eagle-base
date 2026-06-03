"""Live position and P&L monitor.

Runs a polling loop that fetches live positions from the active broker
and emits updates via an in-memory event bus (or stdout in debug mode).
"""

from __future__ import annotations

import time
from typing import Callable

from brokers.base import BrokerBase
from brokers.models import BrokerPosition
from core.logger import get_logger

logger = get_logger(__name__)

_PositionCallback = Callable[[list[BrokerPosition]], None]


class PositionMonitor:
    """Polls broker for live positions and calls registered callbacks."""

    def __init__(
        self,
        broker: BrokerBase,
        poll_interval: float = 5.0,
    ) -> None:
        self._broker = broker
        self._poll_interval = poll_interval
        self._callbacks: list[_PositionCallback] = []
        self._running: bool = False

    def register(self, callback: _PositionCallback) -> None:
        """Register a callback to be called on each position update."""
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start the blocking polling loop."""
        self._running = True
        logger.info(
            "PositionMonitor started (broker=%s, interval=%.1fs)",
            self._broker.name,
            self._poll_interval,
        )
        try:
            while self._running:
                self._tick()
                time.sleep(self._poll_interval)
        except KeyboardInterrupt:
            logger.info("PositionMonitor stopped by user")
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    def _tick(self) -> None:
        try:
            positions = self._broker.get_positions()
            for cb in self._callbacks:
                cb(positions)
        except Exception as exc:
            logger.exception("PositionMonitor tick error: %s", exc)


def log_positions(positions: list[BrokerPosition]) -> None:
    """Default callback — logs positions to stdout."""
    for p in positions:
        logger.info(
            "[%s] %s qty=%d avg=%.2f ltp=%.2f pnl=%.2f",
            p.exchange, p.symbol, p.quantity,
            p.avg_price, p.ltp, p.pnl,
        )
