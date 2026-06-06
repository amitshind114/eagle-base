"""Eagle-Base Order Domain Model.

Full order lifecycle: PENDING → OPEN → FILLED/CANCELLED/REJECTED.
Supports MARKET, LIMIT, STOP, STOP_LIMIT order types.

Factory method `Order.create()` runs the risk gate before constructing
an order — every order request is validated against daily limits,
position size, and VIX regime before a broker ever sees it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.logger import logger
from domain.enums import (
    Exchange,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)


class OrderEvent(BaseModel):
    """Immutable audit record of an order state change."""
    model_config = {"frozen": True}

    timestamp: datetime = Field(default_factory=lambda: datetime.now())
    from_status: OrderStatus
    to_status: OrderStatus
    notes: str = ""


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
    OrderStatus.FILLED:    set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED:  set(),
    OrderStatus.EXPIRED:   set(),
}


class Order(BaseModel):
    """Trading order with full lifecycle management and pre-trade risk gate."""

    model_config = {"frozen": False, "validate_assignment": True}

    order_id:         str             = Field(default_factory=lambda: str(uuid.uuid4()))
    broker_order_id:  Optional[str]   = Field(default=None)
    symbol:           str
    exchange:         Exchange
    side:             OrderSide
    order_type:       OrderType
    quantity:         int             = Field(..., ge=1)
    filled_quantity:  int             = Field(default=0, ge=0)
    pending_quantity: int             = Field(default=0, ge=0)
    price:            Optional[float] = Field(default=None, gt=0)
    stop_price:       Optional[float] = Field(default=None, gt=0)
    average_price:    float           = Field(default=0.0, ge=0)
    status:           OrderStatus     = Field(default=OrderStatus.PENDING)
    time_in_force:    TimeInForce     = Field(default=TimeInForce.DAY)
    tag:              str             = Field(default="")
    rejection_reason: Optional[str]   = Field(default=None)
    created_at:       datetime        = Field(default_factory=lambda: datetime.now())
    updated_at:       datetime        = Field(default_factory=lambda: datetime.now())
    filled_at:        Optional[datetime] = Field(default=None)
    history:          List[OrderEvent]   = Field(default_factory=list)

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
        # Use object.__setattr__ to bypass validate_assignment and avoid recursion
        object.__setattr__(self, "pending_quantity", max(0, self.quantity - self.filled_quantity))
        return self

    # ── Factory: risk-gated order construction ────────────────────────────

    @classmethod
    def create(
        cls,
        symbol: str,
        exchange: Exchange,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        tag: str = "",
        capital: float | None = None,
        prices: dict | None = None,
        portfolio: dict | None = None,
        vix: float | None = None,
        upcoming_events: dict | None = None,
        session: str = "live",
    ) -> "Order":
        """Construct an Order only if the risk gate permits it.

        Runs `risk.gate.compute_allowed_actions()` before creating the order.
        Raises ValueError with the block reason if the gate rejects the trade.
        Caps quantity at `allowed.max_qty` if the gate permits but restricts size.

        All non-risk keyword arguments match the Order field names directly.
        """
        from core.audit import audit
        from risk.gate import compute_allowed_actions

        sym = symbol.strip().upper()
        allowed = compute_allowed_actions(
            symbol=sym,
            exchange=exchange.value if hasattr(exchange, "value") else str(exchange),
            capital=capital,
            prices=prices,
            portfolio=portfolio,
            vix=vix,
            upcoming_events=upcoming_events,
        )

        if not allowed:
            audit.record(
                "GATE_BLOCK", sym, session=session,
                reason=allowed.block_reason, flags=allowed.flags,
            )
            raise ValueError(
                f"Order blocked by risk gate [{sym}]: {allowed.block_reason}"
            )

        if allowed.warnings:
            for w in allowed.warnings:
                logger.warning(f"[risk] {sym}: {w}")

        safe_qty = min(quantity, allowed.max_qty) if allowed.max_qty > 0 else quantity
        if safe_qty < quantity:
            logger.info(
                f"[risk] {sym}: quantity reduced {quantity} → {safe_qty} "
                f"(gate max_qty={allowed.max_qty})"
            )

        audit.record(
            "ORDER_CREATED", sym, session=session,
            side=side.value if hasattr(side, "value") else str(side),
            qty=safe_qty, flags=allowed.flags,
        )

        return cls(
            symbol=sym,
            exchange=exchange,
            side=side,
            order_type=order_type,
            quantity=safe_qty,
            price=price,
            stop_price=stop_price,
            tag=tag,
        )

    # ── Lifecycle methods ─────────────────────────────────────────────────

    def transition(self, new_status: OrderStatus, notes: str = "") -> None:
        allowed = _VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {self.status.value} → {new_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        event = OrderEvent(from_status=self.status, to_status=new_status, notes=notes)
        self.history.append(event)
        self.status = new_status
        self.updated_at = datetime.now()
        logger.debug(f"Order {self.order_id[:8]}: {event.from_status.value} → {new_status.value}")

    def fill(self, filled_qty: int, fill_price: float) -> None:
        if filled_qty <= 0:
            raise ValueError("fill quantity must be positive")
        if fill_price <= 0:
            raise ValueError("fill price must be positive")
        total_value       = self.average_price * self.filled_quantity + fill_price * filled_qty
        new_filled        = self.filled_quantity + filled_qty
        new_avg           = total_value / new_filled
        new_pending       = max(0, self.quantity - new_filled)
        # Use object.__setattr__ to avoid validate_assignment recursion
        object.__setattr__(self, "filled_quantity", new_filled)
        object.__setattr__(self, "average_price", new_avg)
        object.__setattr__(self, "pending_quantity", new_pending)
        object.__setattr__(self, "updated_at", datetime.now())
        if new_filled >= self.quantity:
            object.__setattr__(self, "filled_at", datetime.now())
            self.transition(OrderStatus.FILLED, notes=f"Filled @ {fill_price:.2f}")
        else:
            self.transition(
                OrderStatus.PARTIALLY_FILLED,
                notes=f"Partial {new_filled}/{self.quantity} @ {fill_price:.2f}",
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
        return self.filled_quantity / self.quantity if self.quantity > 0 else 0.0

    def __str__(self) -> str:
        return (
            f"Order[{self.order_id[:8]}] {self.side.value} {self.quantity} {self.symbol} "
            f"{self.order_type.value} status={self.status.value} "
            f"filled={self.filled_quantity}/{self.quantity} avg={self.average_price:.2f}"
        )
