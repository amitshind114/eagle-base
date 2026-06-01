"""Eagle-Base Domain Enumerations.

All enums used across domain models. Centralised here
to prevent circular imports and ensure consistency.
"""

from __future__ import annotations

from enum import Enum, auto


class Exchange(str, Enum):
    """Supported exchanges."""
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"   # NSE F&O
    BFO = "BFO"   # BSE F&O
    MCX = "MCX"
    CDS = "CDS"   # Currency derivatives


class InstrumentType(str, Enum):
    """Instrument type classification."""
    EQ = "EQ"         # Equity / stock
    FUT = "FUT"       # Futures
    CE = "CE"         # Call option
    PE = "PE"         # Put option
    INDEX = "INDEX"   # Index (non-tradeable reference)
    ETF = "ETF"       # Exchange-traded fund
    BOND = "BOND"     # Bond


class OptionType(str, Enum):
    """Option contract type."""
    CE = "CE"
    PE = "PE"
    NA = "NA"  # Not an option


class OrderSide(str, Enum):
    """Order direction."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order execution type."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"             # Stop-loss market
    STOP_LIMIT = "STOP_LIMIT" # Stop-loss limit


class OrderStatus(str, Enum):
    """Lifecycle states of an order."""
    PENDING = "PENDING"       # Created, not yet sent
    OPEN = "OPEN"             # Sent to broker, awaiting fill
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SignalDirection(str, Enum):
    """Trading signal direction."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"


class PositionSide(str, Enum):
    """Position direction."""
    LONG = "LONG"
    SHORT = "SHORT"


class TimeInForce(str, Enum):
    """Order time-in-force policy."""
    DAY = "DAY"     # Valid for the trading day
    IOC = "IOC"     # Immediate or cancel
    GTC = "GTC"     # Good till cancelled
    GTD = "GTD"     # Good till date
