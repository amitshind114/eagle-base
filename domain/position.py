"""Eagle-Base Position Domain Model.

Tracks a live open position.
Calculates unrealized PnL, realized PnL, average entry,
average exit, and exposure in real time.
"""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from domain.enums import Exchange, PositionSide
from domain.trade import Trade
from core.logger import logger


class Position(BaseModel):
    """Open trading position with real-time PnL calculation.

    Handles multiple partial fills via weighted average entry.
    Closing a position (full or partial) produces a Trade.
    """

    model_config = {"frozen": False, "validate_assignment": True}

    position_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    exchange: Exchange
    side: PositionSide
    quantity: int = Field(default=0, ge=0)
    average_entry_price: float = Field(default=0.0, ge=0)
    last_price: float = Field(default=0.0, ge=0)
    realized_pnl: float = Field(default=0.0)
    commission_paid: float = Field(default=0.0, ge=0)
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    strategy_name: str = Field(default="")
    trades: List[Trade] = Field(default_factory=list)
    is_open: bool = Field(default=True)

    @property
    def unrealized_pnl(self) -> float:
        """Mark-to-market PnL using last_price."""
        if self.last_price == 0 or self.quantity == 0:
            return 0.0
        if self.side == PositionSide.LONG:
            return (self.last_price - self.average_entry_price) * self.quantity
        else:  # SHORT
            return (self.average_entry_price - self.last_price) * self.quantity

    @property
    def total_pnl(self) -> float:
        """Realized + Unrealized PnL."""
        return self.realized_pnl + self.unrealized_pnl

    @property
    def exposure(self) -> float:
        """Notional value of the open position."""
        return self.average_entry_price * self.quantity

    @property
    def current_exposure(self) -> float:
        """Current market value of open position."""
        return self.last_price * self.quantity

    @property
    def return_pct(self) -> float:
        """Unrealized return as percentage of entry exposure."""
        if self.exposure == 0:
            return 0.0
        return (self.unrealized_pnl / self.exposure) * 100

    def add_fill(self, fill_qty: int, fill_price: float, commission: float = 0.0) -> None:
        """Add a new fill to this position (weighted average entry)."""
        if fill_qty <= 0:
            raise ValueError("fill_qty must be positive")
        if fill_price <= 0:
            raise ValueError("fill_price must be positive")
        total_value = self.average_entry_price * self.quantity + fill_price * fill_qty
        self.quantity += fill_qty
        self.average_entry_price = total_value / self.quantity
        self.commission_paid += commission
        self.updated_at = datetime.now(UTC)
        logger.debug(
            f"Position {self.symbol}: +{fill_qty} @ {fill_price:.2f} "
            f"avg_entry={self.average_entry_price:.2f} qty={self.quantity}"
        )

    def close_partial(self, close_qty: int, exit_price: float, commission: float = 0.0) -> Trade:
        """Partially or fully close a position. Returns a Trade."""
        if close_qty <= 0:
            raise ValueError("close_qty must be positive")
        if close_qty > self.quantity:
            raise ValueError(
                f"Cannot close {close_qty} units — position only has {self.quantity}"
            )
        if exit_price <= 0:
            raise ValueError("exit_price must be positive")

        # Realize PnL for the closed portion
        if self.side == PositionSide.LONG:
            pnl = (exit_price - self.average_entry_price) * close_qty
        else:
            pnl = (self.average_entry_price - exit_price) * close_qty

        net_pnl = pnl - commission
        self.realized_pnl += net_pnl
        self.commission_paid += commission
        self.quantity -= close_qty
        self.updated_at = datetime.now(UTC)

        if self.quantity == 0:
            self.is_open = False

        trade = Trade(
            symbol=self.symbol,
            exchange=self.exchange,
            side=self.side,
            quantity=close_qty,
            entry_price=self.average_entry_price,
            exit_price=exit_price,
            entry_time=self.opened_at,
            exit_time=datetime.now(UTC),
            commission=commission,
            strategy_name=self.strategy_name,
        )
        self.trades.append(trade)

        logger.info(
            f"Position {self.symbol}: closed {close_qty} @ {exit_price:.2f} "
            f"realized_pnl={net_pnl:.2f} remaining_qty={self.quantity}"
        )
        return trade

    def close(self, exit_price: float, commission: float = 0.0) -> Trade:
        """Fully close the position."""
        return self.close_partial(self.quantity, exit_price, commission)

    def update_last_price(self, price: float) -> None:
        """Update mark-to-market price."""
        if price <= 0:
            raise ValueError("price must be positive")
        self.last_price = price

    def __str__(self) -> str:
        status = "OPEN" if self.is_open else "CLOSED"
        return (
            f"Position[{self.symbol}|{self.side.value}] qty={self.quantity} "
            f"entry={self.average_entry_price:.2f} last={self.last_price:.2f} "
            f"unrealized={self.unrealized_pnl:.2f} realized={self.realized_pnl:.2f} [{status}]"
        )
