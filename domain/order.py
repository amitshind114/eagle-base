"""Eagle-Base Order Domain Model.

Full order lifecycle: PENDING → OPEN → FILLED/CANCELLED/REJECTED.
Supports MARKET, LIMIT, STOP, STOP_LIMIT order types.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from domain.enums import (
    Exchange,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from core.logger import logger


class OrderEvent(BaseModel):
    """Immutable audit record of an order state change."""
    model_config = {"frozen": True}

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    from_status: OrderStatus
    to_status: OrderStatus
    notes: str = ""


# Valid order state transitions
_VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.OPEN, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.OPEN: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.EXPIRED: set(),
}


class Order(BaseModel):
    """Trading order with full lifecycle management.

    Order state transitions are validated.
    Limit orders must have a price.
    Stop orders must have a stop_price.
    """

    model_config = {"frozen": False, "validate_assignment": True}

    order_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    broker_order_id: Optional[str] = Field(default=None)
    symbol: str
    exchange: Exchange
    side: OrderSide
    order_type: OrderType
    quantity: int = Field(..., ge=1)
    filled_quantity: int = Field(default=0, ge=0)
    pending_quantity: int = Field(default=0, ge=0)
    price: Optional[float] = Field(default=None, gt=0, description="Limit price")
    stop_price: Optional[float] = Field(default=None, gt=0, description="Stop trigger price")
    average_price: float = Field(default=0.0, ge=0)
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    time_in_force: TimeInForce = Field(default=TimeInForce.DAY)
    tag: str = Field(default="", description="Strategy or user tag")
    rejection_reason: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = Field(default=None)
    history: List[OrderEvent] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def validate_price_requirements(self) -> "Order":
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("LIMIT order requires a price")
        if self.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and self.stop_price is None:
            raise ValueError(f"{self.order_type.value} order requires a stop_price")
        if self.order_type == OrderType.STOP_LIMIT and self.price is None:
            raise ValueError("STOP_LIMIT order requires both price and stop_price")
        return self

    @model_validator(mode="after")
    def sync_pending_quantity(self) -> "Order":
        self.pending_quantity = max(0, self.quantity - self.filled_quantity)
        return self

    def transition(self, new_status: OrderStatus, notes: str = "") -> None:
        """Perform a validated state transition."""
        allowed = _VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {self.status.value} → {new_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        event = OrderEvent(from_status=self.status, to_status=new_status, notes=notes)
        self.history.append(event)
        self.status = new_status
        self.updated_at = datetime.utcnow()
        logger.debug(f"Order {self.order_id[:8]}: {event.from_status.value} → {new_status.value}")

    def fill(self, filled_qty: int, fill_price: float) -> None:
        """Record a (partial) fill."""
        if filled_qty <= 0:
            raise ValueError("fill quantity must be positive")
        if fill_price <= 0:
            raise ValueError("fill price must be positive")
        total_value = self.average_price * self.filled_quantity + fill_price * filled_qty
        self.filled_quantity += filled_qty
        self.average_price = total_value / self.filled_quantity
        self.pending_quantity = max(0, self.quantity - self.filled_quantity)
        self.updated_at = datetime.utcnow()
        if self.filled_quantity >= self.quantity:
            self.filled_at = datetime.utcnow()
            self.transition(OrderStatus.FILLED, notes=f"Filled @ {fill_price:.2f}")
        else:
            self.transition(
                OrderStatus.PARTIALLY_FILLED,
                notes=f"Partial fill {self.filled_quantity}/{self.quantity} @ {fill_price:.2f}",
            )

    def cancel(self, reason: str = "") -> None:
        self.transition(OrderStatus.CANCELLED, notes=reason)

    def reject(self, reason: str) -> None:
        self.rejection_reason = reason
        self.transition(OrderStatus.REJECTED, notes=reason)

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )

    @property
    def fill_ratio(self) -> float:
        """Fraction of order filled [0.0 - 1.0]."""
        return self.filled_quantity / self.quantity if self.quantity > 0 else 0.0

    def __str__(self) -> str:
        return (
            f"Order[{self.order_id[:8]}] {self.side.value} {self.quantity} {self.symbol} "
            f"{self.order_type.value} status={self.status.value} "
            f"filled={self.filled_quantity}/{self.quantity} avg={self.average_price:.2f}"
        )
