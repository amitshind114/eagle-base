"""OrderBook — Phase 8 Paper Trading.

Manages the lifecycle of paper orders:
  PENDING → FILLED / REJECTED / CANCELLED

Usage:
    ob = OrderBook()
    oid = ob.place(Order(order_id="O1", symbol="RELIANCE", side=OrderSide.BUY,
                         order_type=OrderType.MARKET, quantity=10))
    trade = ob.fill(oid, price=2500.0)
    ob.get_pending()   # []
    ob.get_filled()    # [Order(...)]
"""

from __future__ import annotations

import uuid
from typing import Optional

from core.logger import get_logger
from paper.models import Order, OrderSide, OrderStatus, OrderType

log = get_logger("paper.order_book")


class OrderBook:
    """In-memory order lifecycle manager."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}   # order_id → Order

    # ------------------------------------------------------------------
    # Mutating operations
    # ------------------------------------------------------------------

    def place(self, order: Order) -> str:
        """Register a new PENDING order. Returns its order_id."""
        if not order.order_id:
            order = order.model_copy(update={"order_id": str(uuid.uuid4())})
        order = order.model_copy(update={"status": OrderStatus.PENDING})
        self._orders[order.order_id] = order
        log.debug(f"[order_book] PLACED {order.order_id} {order.side} {order.symbol} x{order.quantity}")
        return order.order_id

    def cancel(self, order_id: str) -> bool:
        """Cancel a PENDING order. Returns True if cancelled, False otherwise."""
        order = self._orders.get(order_id)
        if order is None:
            log.warning(f"[order_book] cancel: unknown order {order_id}")
            return False
        if order.status != OrderStatus.PENDING:
            log.warning(f"[order_book] cancel: order {order_id} is {order.status}, not PENDING")
            return False
        self._orders[order_id] = order.model_copy(update={"status": OrderStatus.CANCELLED})
        log.info(f"[order_book] CANCELLED {order_id}")
        return True

    def fill(self, order_id: str, price: float) -> Optional[Order]:
        """Mark a PENDING order as FILLED at the given execution price.

        Returns the filled Order, or None if order not found / already closed.
        """
        order = self._orders.get(order_id)
        if order is None:
            log.warning(f"[order_book] fill: unknown order {order_id}")
            return None
        if order.status != OrderStatus.PENDING:
            log.warning(f"[order_book] fill: order {order_id} is {order.status}, cannot fill")
            return None
        filled = order.model_copy(update={"status": OrderStatus.FILLED, "exec_price": price})
        self._orders[order_id] = filled
        log.info(f"[order_book] FILLED {order_id} @ {price}")
        return filled

    def reject(self, order_id: str, reason: str = "") -> bool:
        """Mark a PENDING order as REJECTED."""
        order = self._orders.get(order_id)
        if order is None or order.status != OrderStatus.PENDING:
            return False
        self._orders[order_id] = order.model_copy(
            update={"status": OrderStatus.REJECTED, "notes": reason}
        )
        log.warning(f"[order_book] REJECTED {order_id}: {reason}")
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def get_pending(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status == OrderStatus.PENDING]

    def get_filled(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status == OrderStatus.FILLED]

    def get_rejected(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status == OrderStatus.REJECTED]

    def get_cancelled(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status == OrderStatus.CANCELLED]

    def all(self) -> list[Order]:
        return list(self._orders.values())

    def __len__(self) -> int:
        return len(self._orders)

    def __repr__(self) -> str:
        pending  = len(self.get_pending())
        filled   = len(self.get_filled())
        rejected = len(self.get_rejected())
        return f"<OrderBook pending={pending} filled={filled} rejected={rejected}>"
