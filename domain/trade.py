"""Eagle-Base Trade Domain Model.

A completed round-trip trade (entry + exit).
Calculates realized PnL, holding period, and return metrics.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from domain.enums import Exchange, OrderSide, PositionSide


class Trade(BaseModel):
    """A completed trade: entry order → exit order.

    Realized PnL accounts for side (long vs short),
    quantity, entry/exit prices, and commission.
    """

    model_config = {"frozen": True}

    trade_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    exchange: Exchange
    side: PositionSide
    quantity: int = Field(..., ge=1)
    entry_price: float = Field(..., gt=0)
    exit_price: float = Field(..., gt=0)
    entry_time: datetime
    exit_time: datetime
    commission: float = Field(default=0.0, ge=0)
    strategy_name: str = Field(default="")
    signal_id: Optional[str] = Field(default=None)
    notes: str = Field(default="")

    @model_validator(mode="after")
    def validate_times(self) -> "Trade":
        if self.exit_time < self.entry_time:
            raise ValueError(
                f"exit_time ({self.exit_time}) cannot be before entry_time ({self.entry_time})"
            )
        return self

    @property
    def gross_pnl(self) -> float:
        """PnL before commissions."""
        if self.side == PositionSide.LONG:
            return (self.exit_price - self.entry_price) * self.quantity
        else:  # SHORT
            return (self.entry_price - self.exit_price) * self.quantity

    @property
    def net_pnl(self) -> float:
        """PnL after commissions."""
        return self.gross_pnl - self.commission

    @property
    def return_pct(self) -> float:
        """Percentage return on capital deployed."""
        capital = self.entry_price * self.quantity
        if capital == 0:
            return 0.0
        return (self.net_pnl / capital) * 100

    @property
    def holding_period_seconds(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds()

    @property
    def holding_period_days(self) -> float:
        return self.holding_period_seconds / 86400

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0

    @property
    def is_loser(self) -> bool:
        return self.net_pnl < 0

    @property
    def mae(self) -> Optional[float]:
        """Maximum adverse excursion — placeholder for future tick data."""
        return None

    def __str__(self) -> str:
        direction = "WIN" if self.is_winner else "LOSS"
        return (
            f"Trade[{self.trade_id[:8]}] {self.side.value} {self.quantity} {self.symbol} "
            f"Entry={self.entry_price:.2f} Exit={self.exit_price:.2f} "
            f"PnL={self.net_pnl:.2f} ({self.return_pct:.2f}%) [{direction}]"
        )
