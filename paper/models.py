"""Paper trading domain models."""

from __future__ import annotations

import datetime
from enum import Enum

from pydantic import BaseModel


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Order(BaseModel):
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: float = 0.0
    exec_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    timestamp: datetime.datetime = datetime.datetime.now()
    pnl: float = 0.0
    notes: str = ""


class Position(BaseModel):
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealised_pnl(self) -> float:
        return (self.current_price - self.avg_cost) * self.quantity


class Portfolio(BaseModel):
    cash: float
    positions: dict[str, Position] = {}
    orders: list[Order] = []

    @property
    def total_value(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())
