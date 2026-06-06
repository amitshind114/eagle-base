"""TradeBook — Phase 8 Paper Trading.

Records every filled trade and tracks realized P&L.
A Trade is created from a filled Order once the position delta is known.

Usage:
    tb = TradeBook()
    tb.add(Trade(trade_id="T1", order_id="O1", symbol="RELIANCE",
                 side=OrderSide.BUY, quantity=10, price=2500.0,
                 realized_pnl=0.0))
    tb.today()                  # trades from today
    tb.by_symbol("RELIANCE")    # all trades for RELIANCE
    tb.realized_pnl()           # sum of all realized P&L
    tb.export_csv()             # CSV string
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime
from dataclasses import dataclass, field
from typing import Optional

from core.logger import get_logger
from paper.models import OrderSide

log = get_logger("paper.trade_book")


@dataclass
class Trade:
    """Immutable record of a filled order becoming a trade."""
    trade_id:     str
    order_id:     str
    symbol:       str
    side:         OrderSide
    quantity:     int
    price:        float            # execution price (after slippage)
    realized_pnl: float = 0.0     # non-zero only on closing trades
    timestamp:    datetime = field(default_factory=datetime.now)
    notes:        str = ""

    @property
    def value(self) -> float:
        """Gross trade value (qty × price)."""
        return self.quantity * self.price

    def to_dict(self) -> dict:
        return {
            "trade_id":     self.trade_id,
            "order_id":     self.order_id,
            "symbol":       self.symbol,
            "side":         self.side.value,
            "quantity":     self.quantity,
            "price":        self.price,
            "value":        self.value,
            "realized_pnl": self.realized_pnl,
            "timestamp":    self.timestamp.isoformat(),
            "notes":        self.notes,
        }


class TradeBook:
    """In-memory trade ledger with P&L tracking."""

    def __init__(self) -> None:
        self._trades: list[Trade] = []

    # ------------------------------------------------------------------
    # Mutating
    # ------------------------------------------------------------------

    def add(self, trade: Trade) -> None:
        """Append a trade to the ledger."""
        if not trade.trade_id:
            object.__setattr__(trade, "trade_id", str(uuid.uuid4()))
        self._trades.append(trade)
        log.info(
            f"[trade_book] {trade.side.value} {trade.symbol} "
            f"x{trade.quantity} @ {trade.price:.2f} "
            f"pnl={trade.realized_pnl:+.2f}"
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all(self) -> list[Trade]:
        return list(self._trades)

    def today(self) -> list[Trade]:
        today = date.today()
        return [t for t in self._trades if t.timestamp.date() == today]

    def by_symbol(self, symbol: str) -> list[Trade]:
        return [t for t in self._trades if t.symbol == symbol]

    def realized_pnl(self) -> float:
        """Sum of all realized P&L across closed trades."""
        return sum(t.realized_pnl for t in self._trades)

    def daily_pnl(self) -> dict[str, float]:
        """Return {date_str: realized_pnl} grouped by trade date."""
        result: dict[str, float] = {}
        for t in self._trades:
            key = t.timestamp.date().isoformat()
            result[key] = result.get(key, 0.0) + t.realized_pnl
        return result

    def symbol_pnl(self) -> dict[str, float]:
        """Return {symbol: total_realized_pnl}."""
        result: dict[str, float] = {}
        for t in self._trades:
            result[t.symbol] = result.get(t.symbol, 0.0) + t.realized_pnl
        return result

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_csv(self) -> str:
        """Return all trades as a CSV string."""
        if not self._trades:
            return ""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(self._trades[0].to_dict().keys()))
        writer.writeheader()
        writer.writerows(t.to_dict() for t in self._trades)
        return buf.getvalue()

    def __len__(self) -> int:
        return len(self._trades)

    def __repr__(self) -> str:
        return (
            f"<TradeBook trades={len(self._trades)} "
            f"realized_pnl={self.realized_pnl():+.2f}>"
        )
