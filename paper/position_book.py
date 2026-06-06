"""PositionBook — Phase 8 Paper Trading.

Tracks open positions, marks them to market, and computes unrealized P&L.
Updates positions automatically when a Trade is added (FIFO cost basis).

Usage:
    pb = PositionBook()
    pb.update(trade)                          # open/add/reduce/close position
    pb.get("RELIANCE")                        # Position | None
    pb.all_open()                             # list of open positions
    pb.unrealized_pnl({"RELIANCE": 2600.0})   # float
    pb.mark_to_market({"RELIANCE": 2600.0})   # DataFrame
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from core.logger import get_logger
from paper.models import OrderSide, Position
from paper.trade_book import Trade

log = get_logger("paper.position_book")


class PositionBook:
    """FIFO position tracker.

    Each Trade either:
      - Opens / adds to a position (same-side)
      - Reduces / closes a position (opposite-side)
    """

    def __init__(self) -> None:
        # symbol → Position (only open positions kept; closed ones removed)
        self._positions: dict[str, Position] = {}
        # symbol → running realized P&L from this position
        self._realized: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(self, trade: Trade) -> float:
        """Apply a trade to the position book.

        Returns realized P&L from this trade (0.0 for opening trades).
        """
        symbol = trade.symbol
        existing = self._positions.get(symbol)

        if existing is None or existing.quantity == 0:
            # Opening a new position
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=trade.quantity,
                avg_cost=trade.price,
                current_price=trade.price,
            )
            log.info(
                f"[pos_book] OPEN {symbol} x{trade.quantity} @ {trade.price:.2f}"
            )
            return 0.0

        # Existing position — same or opposite side?
        if trade.side == OrderSide.BUY:
            # Adding to a long (or closing a short — simplified: treat as long)
            new_qty = existing.quantity + trade.quantity
            new_avg = (
                (existing.avg_cost * existing.quantity + trade.price * trade.quantity)
                / new_qty
            )
            self._positions[symbol] = existing.model_copy(
                update={"quantity": new_qty, "avg_cost": new_avg, "current_price": trade.price}
            )
            log.info(f"[pos_book] ADD {symbol} x{trade.quantity} @ {trade.price:.2f} avg={new_avg:.2f}")
            return 0.0
        else:
            # SELL — reducing or closing a long position
            realized = (trade.price - existing.avg_cost) * trade.quantity
            new_qty  = existing.quantity - trade.quantity
            self._realized[symbol] = self._realized.get(symbol, 0.0) + realized

            if new_qty <= 0:
                # Position closed
                del self._positions[symbol]
                log.info(
                    f"[pos_book] CLOSE {symbol} x{trade.quantity} @ {trade.price:.2f} "
                    f"realized={realized:+.2f}"
                )
            else:
                self._positions[symbol] = existing.model_copy(
                    update={"quantity": new_qty, "current_price": trade.price}
                )
                log.info(
                    f"[pos_book] REDUCE {symbol} x{trade.quantity} @ {trade.price:.2f} "
                    f"remaining={new_qty} realized={realized:+.2f}"
                )
            return realized

    # ------------------------------------------------------------------
    # Marking to market
    # ------------------------------------------------------------------

    def mark_to_market(self, prices: dict[str, float]) -> pd.DataFrame:
        """Update current_price for all open positions and return a summary DataFrame."""
        rows = []
        for symbol, pos in self._positions.items():
            price = prices.get(symbol, pos.current_price)
            updated = pos.model_copy(update={"current_price": price})
            self._positions[symbol] = updated
            rows.append({
                "symbol":       symbol,
                "quantity":     pos.quantity,
                "avg_cost":     round(pos.avg_cost, 2),
                "current_price":round(price, 2),
                "market_value": round(updated.market_value, 2),
                "unrealized_pnl": round(updated.unrealised_pnl, 2),
            })
        return pd.DataFrame(rows)

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        """Compute total unrealized P&L given a price dict."""
        total = 0.0
        for symbol, pos in self._positions.items():
            price = prices.get(symbol, pos.current_price)
            total += (price - pos.avg_cost) * pos.quantity
        return round(total, 2)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def all_open(self) -> list[Position]:
        return list(self._positions.values())

    def symbols(self) -> list[str]:
        return list(self._positions.keys())

    def position_count(self) -> int:
        return len(self._positions)

    def total_realized(self) -> float:
        return round(sum(self._realized.values()), 2)

    def __repr__(self) -> str:
        return (
            f"<PositionBook open={len(self._positions)} "
            f"realized={self.total_realized():+.2f}>"
        )
