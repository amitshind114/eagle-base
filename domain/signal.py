"""Eagle-Base Signal Domain Model.

Trading signal produced by a strategy.
Carries direction, strength, metadata, and source instrument.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from domain.enums import SignalDirection


class Signal(BaseModel):
    """Trading signal emitted by a strategy.

    Strength is normalised to [0.0, 1.0].
    1.0 = maximum confidence, 0.0 = weakest valid signal.
    """

    model_config = {"frozen": True}

    signal_id: str = Field(..., description="Unique signal identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    symbol: str
    exchange: str
    direction: SignalDirection
    strength: float = Field(default=1.0, ge=0.0, le=1.0, description="Signal confidence [0-1]")
    price: float = Field(..., gt=0, description="Reference price at signal generation")
    strategy_name: str = Field(default="")
    timeframe: str = Field(default="1d")
    entry_price: Optional[float] = Field(default=None, gt=0)
    target_price: Optional[float] = Field(default=None, gt=0)
    stop_loss: Optional[float] = Field(default=None, gt=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="")

    @field_validator("symbol", "exchange")
    @classmethod
    def uppercase(cls, v: str) -> str:
        return v.strip().upper()

    @property
    def risk_reward(self) -> Optional[float]:
        """Calculate risk/reward ratio if target and stop_loss are set."""
        if self.entry_price and self.target_price and self.stop_loss:
            if self.direction == SignalDirection.BUY:
                reward = self.target_price - self.entry_price
                risk = self.entry_price - self.stop_loss
            else:
                reward = self.entry_price - self.target_price
                risk = self.stop_loss - self.entry_price
            if risk <= 0:
                return None
            return round(reward / risk, 2)
        return None

    @property
    def is_actionable(self) -> bool:
        """Signal is actionable if direction is not HOLD."""
        return self.direction not in (SignalDirection.HOLD,)

    def __str__(self) -> str:
        rr = f" RR={self.risk_reward:.2f}" if self.risk_reward else ""
        return (
            f"Signal[{self.signal_id}] {self.direction.value} {self.symbol} "
            f"@ {self.price:.2f} strength={self.strength:.2f}{rr}"
        )
