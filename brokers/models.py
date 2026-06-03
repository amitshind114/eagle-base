"""Broker-agnostic data models shared across all adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class ProductType(str, Enum):
    INTRADAY = "INTRADAY"   # MIS
    DELIVERY = "DELIVERY"   # CNC
    NORMAL = "NORMAL"       # NRML (F&O)
    CARRYFORWARD = "CARRYFORWARD"


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"   # NSE F&O
    BFO = "BFO"   # BSE F&O
    MCX = "MCX"
    CDS = "CDS"


@dataclass
class BrokerOrder:
    """Unified order payload — adapter maps this to broker-specific fields."""

    symbol: str
    token: str
    exchange: Exchange
    side: OrderSide
    order_type: OrderType
    product: ProductType
    quantity: int
    price: float = 0.0
    trigger_price: float = 0.0
    tag: str = ""
    variety: str = "NORMAL"  # broker-specific variety/segment


@dataclass
class BrokerPosition:
    symbol: str
    token: str
    exchange: str
    product: str
    quantity: int
    avg_price: float
    ltp: float
    pnl: float
    day_buy_qty: int = 0
    day_sell_qty: int = 0


@dataclass
class BrokerProfile:
    client_id: str
    name: str
    email: str
    broker: str
    exchanges: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
