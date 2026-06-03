"""Paper trading broker — simulates order execution with live prices."""

from __future__ import annotations

import uuid
import datetime

from core.config import settings
from core.exceptions import InsufficientFundsError, RiskBreachError
from core.logger import get_logger
from data.fetcher import DataFetcher
from .models import Order, OrderSide, OrderStatus, OrderType, Portfolio, Position

log = get_logger("paper.broker")
fetcher = DataFetcher()


class PaperBroker:
    """Simulate order execution against live yfinance prices."""

    def __init__(self, capital: float | None = None) -> None:
        self.portfolio = Portfolio(cash=capital or settings.paper_capital)

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        limit_price: float = 0.0,
    ) -> Order:
        """Place a paper order. Returns filled Order."""
        ltp = fetcher.fetch_latest_price(symbol)
        exec_price = limit_price if order_type == "LIMIT" and limit_price > 0 else ltp
        cost = exec_price * quantity
        commission = cost * settings.paper_brokerage_pct / 100
        total_cost = cost + commission
        order = Order(
            order_id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side=OrderSide(side),
            order_type=OrderType(order_type),
            quantity=quantity,
            limit_price=limit_price,
            exec_price=exec_price,
            timestamp=datetime.datetime.now(),
        )
        sym_key = symbol.replace(".NS", "")
        if side == "BUY":
            if total_cost > self.portfolio.cash:
                order.status = OrderStatus.REJECTED
                order.notes = "Insufficient funds"
                log.warning(f"Order rejected: insufficient funds for {symbol}")
                raise InsufficientFundsError(f"Need ₹{total_cost:,.0f}, have ₹{self.portfolio.cash:,.0f}")
            self.portfolio.cash -= total_cost
            if sym_key in self.portfolio.positions:
                pos = self.portfolio.positions[sym_key]
                new_qty = pos.quantity + quantity
                new_avg = (pos.avg_cost * pos.quantity + exec_price * quantity) / new_qty
                self.portfolio.positions[sym_key] = Position(
                    symbol=sym_key, quantity=new_qty, avg_cost=new_avg, current_price=exec_price
                )
            else:
                self.portfolio.positions[sym_key] = Position(
                    symbol=sym_key, quantity=quantity, avg_cost=exec_price, current_price=exec_price
                )
        else:  # SELL
            if sym_key not in self.portfolio.positions or self.portfolio.positions[sym_key].quantity < quantity:
                order.status = OrderStatus.REJECTED
                order.notes = "Insufficient position"
                raise RiskBreachError(f"Not enough {sym_key} to sell {quantity} shares")
            pos = self.portfolio.positions[sym_key]
            pnl = (exec_price - pos.avg_cost) * quantity - commission
            order.pnl = round(pnl, 2)
            self.portfolio.cash += cost - commission
            new_qty = pos.quantity - quantity
            if new_qty == 0:
                del self.portfolio.positions[sym_key]
            else:
                self.portfolio.positions[sym_key] = Position(
                    symbol=sym_key, quantity=new_qty, avg_cost=pos.avg_cost, current_price=exec_price
                )

        order.status = OrderStatus.FILLED
        self.portfolio.orders.append(order)
        log.info(f"Order filled: {side} {quantity} {symbol} @ ₹{exec_price:.2f} | PnL: ₹{order.pnl:+.2f}")
        return order

    def reset(self, capital: float | None = None) -> None:
        self.portfolio = Portfolio(cash=capital or settings.paper_capital)
        log.info(f"Paper portfolio reset to ₹{self.portfolio.cash:,.0f}")
