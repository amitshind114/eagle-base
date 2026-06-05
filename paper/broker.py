"""Paper trading broker — simulates NSE order execution with live prices.

Simulates fills using live yfinance prices with:
    - Risk gate check (daily loss cap, position limits, VIX guard)
    - Accurate NSE charges (STT, brokerage, exchange, SEBI, stamp, GST)
    - TradeLog integration (every fill recorded for post-session reporting)
    - Audit trail via core.audit

Usage:
    from paper.broker import PaperBroker
    broker = PaperBroker(capital=200_000)
    order  = broker.place_order("RELIANCE", "BUY", 5)
    print(broker.portfolio.summary())
    broker.trade_log.to_csv("session.csv")
"""

from __future__ import annotations

import datetime
import uuid

from core.audit import audit
from core.config import settings
from core.exceptions import InsufficientFundsError, RiskBreachError
from core.logger import get_logger
from data.fetcher import DataFetcher
from paper.models import Order, OrderSide, OrderStatus, OrderType, Portfolio, Position
from reporting.trade_log import TradeEntry, TradeLog
from risk.gate import compute_allowed_actions
from risk.limits import risk_limits

log     = get_logger("paper.broker")
fetcher = DataFetcher()

# ── NSE charge constants (Zerodha MIS) ─────────────────────────────────
_BROKERAGE  = 20.0
_STT_SELL   = 0.00025
_EXCHANGE   = 0.0000335
_SEBI       = 0.000001
_STAMP_BUY  = 0.00003
_GST        = 0.18


def _charges(turnover: float, side: str) -> float:
    brokerage = _BROKERAGE
    stt       = turnover * _STT_SELL  if side == "SELL" else 0.0
    exchange  = turnover * _EXCHANGE
    sebi      = turnover * _SEBI
    stamp     = turnover * _STAMP_BUY if side == "BUY"  else 0.0
    gst       = (brokerage + exchange) * _GST
    return round(brokerage + stt + exchange + sebi + stamp + gst, 2)


class PaperBroker:
    """Simulate NSE order execution against live yfinance prices."""

    def __init__(self, capital: float | None = None) -> None:
        self.portfolio  = Portfolio(cash=capital or settings.paper_capital)
        self.trade_log  = TradeLog()
        self._capital   = capital or settings.paper_capital

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        limit_price: float = 0.0,
        strategy: str = "",
        tag: str = "",
    ) -> Order:
        """Place a paper order.  Returns filled Order.

        Raises:
            RiskBreachError      — risk gate blocked the trade
            InsufficientFundsError — not enough cash for a BUY
            RiskBreachError      — not enough position for a SELL
        """
        sym_clean = symbol.replace(".NS", "").upper()
        ltp       = fetcher.fetch_latest_price(symbol)
        prices    = {sym_clean: ltp}

        # ─ Risk gate ───────────────────────────────────────────────────
        portfolio_snapshot = {
            pos_sym: {"qty": pos.quantity, "current_price": pos.current_price, "avg_price": pos.avg_cost}
            for pos_sym, pos in self.portfolio.positions.items()
        }
        allowed = compute_allowed_actions(
            symbol=sym_clean,
            capital=self._capital,
            prices=prices,
            portfolio=portfolio_snapshot,
        )
        if not allowed:
            audit.record("GATE_BLOCK", sym_clean, session="paper",
                         reason=allowed.block_reason, flags=allowed.flags)
            raise RiskBreachError(allowed.block_reason)

        if allowed.warnings:
            for w in allowed.warnings:
                log.warning(f"[risk] {sym_clean}: {w}")

        # ─ Fill price ────────────────────────────────────────────────
        exec_price = limit_price if order_type == "LIMIT" and limit_price > 0 else ltp

        order = Order(
            order_id=str(uuid.uuid4())[:8],
            symbol=sym_clean,
            side=OrderSide(side),
            order_type=OrderType(order_type),
            quantity=quantity,
            limit_price=limit_price,
            exec_price=exec_price,
            timestamp=datetime.datetime.now(),
        )

        turnover = exec_price * quantity
        cost     = _charges(turnover, side)

        if side == "BUY":
            total_cost = turnover + cost
            if total_cost > self.portfolio.cash:
                order.status = OrderStatus.REJECTED
                order.notes  = "Insufficient funds"
                audit.record("ORDER_REJECTED", sym_clean, session="paper",
                             reason="Insufficient funds")
                raise InsufficientFundsError(
                    f"Need ₹{total_cost:,.0f}, have ₹{self.portfolio.cash:,.0f}"
                )
            self.portfolio.cash -= total_cost
            if sym_clean in self.portfolio.positions:
                pos     = self.portfolio.positions[sym_clean]
                new_qty = pos.quantity + quantity
                new_avg = (pos.avg_cost * pos.quantity + exec_price * quantity) / new_qty
                self.portfolio.positions[sym_clean] = Position(
                    symbol=sym_clean, quantity=new_qty,
                    avg_cost=round(new_avg, 4), current_price=exec_price,
                )
            else:
                self.portfolio.positions[sym_clean] = Position(
                    symbol=sym_clean, quantity=quantity,
                    avg_cost=exec_price, current_price=exec_price,
                )

        else:  # SELL
            if sym_clean not in self.portfolio.positions or \
               self.portfolio.positions[sym_clean].quantity < quantity:
                order.status = OrderStatus.REJECTED
                order.notes  = "Insufficient position"
                raise RiskBreachError(f"Not enough {sym_clean} to sell {quantity} shares")

            pos       = self.portfolio.positions[sym_clean]
            gross_pnl = (exec_price - pos.avg_cost) * quantity
            net_pnl   = round(gross_pnl - cost, 2)
            order.pnl = net_pnl

            self.portfolio.cash += (turnover - cost)
            new_qty = pos.quantity - quantity
            if new_qty == 0:
                del self.portfolio.positions[sym_clean]
            else:
                self.portfolio.positions[sym_clean] = Position(
                    symbol=sym_clean, quantity=new_qty,
                    avg_cost=pos.avg_cost, current_price=exec_price,
                )

            # Record completed round-trip in trade log
            entry = TradeEntry.from_fill(
                symbol=sym_clean,
                exchange="NSE",
                side="BUY",          # entry side was BUY; exit is this SELL
                quantity=quantity,
                entry_price=pos.avg_cost,
                exit_price=exec_price,
                product="MIS",
                strategy=strategy,
                tag=tag,
            )
            self.trade_log.add(entry)
            risk_limits.record_trade(sym_clean, "SELL", quantity, exec_price, pnl=net_pnl)

        order.status = OrderStatus.FILLED
        self.portfolio.orders.append(order)
        audit.record("ORDER_FILLED", sym_clean, session="paper",
                     side=side, qty=quantity, price=exec_price, pnl=order.pnl)
        log.info(
            f"Filled: {side} {quantity} {sym_clean} ’ ₹{exec_price:.2f} "
            f"charges=₹{cost:.2f} pnl=₹{order.pnl:+.2f}"
        )
        return order

    def summary(self) -> dict:
        """Portfolio snapshot + trade log summary."""
        return {
            "portfolio": {
                "cash":       round(self.portfolio.cash, 2),
                "positions":  {s: {"qty": p.quantity, "avg": p.avg_cost}
                               for s, p in self.portfolio.positions.items()},
            },
            "trades": self.trade_log.summary(),
        }

    def reset(self, capital: float | None = None) -> None:
        cap = capital or settings.paper_capital
        self.portfolio = Portfolio(cash=cap)
        self.trade_log = TradeLog()
        self._capital  = cap
        log.info(f"Paper portfolio reset to ₹{cap:,.0f}")
