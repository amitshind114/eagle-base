"""Risk Manager — Priority 6.

Pre-trade and portfolio-level risk controls.

TODO (Phase 4 - Priority 6):
- Max position size check
- Max daily loss circuit breaker
- Exposure limits per segment
- Margin utilization check
"""

from __future__ import annotations

from core.logger import logger


class RiskManager:
    """Manages pre-trade risk checks and portfolio risk controls."""

    def __init__(self, max_position_size: float = 100000.0, max_daily_loss: float = 5000.0):
        self.max_position_size = max_position_size
        self.max_daily_loss = max_daily_loss
        self._daily_pnl: float = 0.0

    def check_order(self, symbol: str, qty: int, price: float) -> tuple[bool, str]:
        """Run pre-trade risk check. Returns (approved, reason).

        TODO: Phase 4 Priority 6 — implement actual risk checks.
        """
        raise NotImplementedError("TODO: Phase 4 Priority 6")

    def update_pnl(self, pnl_delta: float) -> None:
        """Update daily PnL tracker. TODO: Phase 4 Priority 6."""
        raise NotImplementedError("TODO: Phase 4 Priority 6")

    def is_circuit_breaker_active(self) -> bool:
        """Check if daily loss limit has been hit. TODO: Phase 4 Priority 6."""
        raise NotImplementedError("TODO: Phase 4 Priority 6")
