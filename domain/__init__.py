"""Eagle-Base Domain Model Layer — Step 1.

All core domain entities for the trading system.
Import from here for clean access:

    from domain import Instrument, Order, Position, Portfolio
"""

from domain.enums import (
    Exchange,
    InstrumentType,
    OptionType,
    OrderSide,
    OrderType,
    OrderStatus,
    SignalDirection,
    PositionSide,
    TimeInForce,
)
from domain.instrument import Instrument
from domain.candle import Candle
from domain.signal import Signal
from domain.order import Order
from domain.trade import Trade
from domain.position import Position
from domain.portfolio import Portfolio
from domain.strategy_context import StrategyContext
from domain.backtest_result import BacktestResult
from domain.risk_rule import RiskRule, RiskRuleSet

__all__ = [
    "Exchange",
    "InstrumentType",
    "OptionType",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "SignalDirection",
    "PositionSide",
    "TimeInForce",
    "Instrument",
    "Candle",
    "Signal",
    "Order",
    "Trade",
    "Position",
    "Portfolio",
    "StrategyContext",
    "BacktestResult",
    "RiskRule",
    "RiskRuleSet",
]
