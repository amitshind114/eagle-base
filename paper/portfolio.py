"""PaperPortfolio — Phase 8 Paper Trading.

Orchestrates OrderBook + TradeBook + PositionBook into one unified interface.
Persists and restores state to/from SQLite so positions survive restarts.

Usage:
    portfolio = PaperPortfolio(cash=500_000.0)
    portfolio.on_signal(signal="BUY", symbol="RELIANCE", price=2500.0, qty=10)
    portfolio.daily_pnl()
    snap = portfolio.snapshot()
    portfolio.persist()     # save to SQLite
    portfolio.restore()     # load from SQLite on startup
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from core.logger import get_logger
from paper.models import Order, OrderSide, OrderStatus, OrderType
from paper.order_book import OrderBook
from paper.position_book import PositionBook
from paper.trade_book import Trade, TradeBook

log = get_logger("paper.portfolio")

DB_PATH = Path("eagle_base/data/paper_portfolio.db")


@dataclass
class PortfolioSnapshot:
    timestamp:        str
    cash:             float
    open_positions:   int
    unrealized_pnl:   float
    realized_pnl:     float
    total_value:      float
    daily_pnl:        float
    total_trades:     int


class PaperPortfolio:
    """Full paper trading portfolio: cash + books + persistence."""

    def __init__(
        self,
        cash: float = 500_000.0,
        db_path: Path = DB_PATH,
    ) -> None:
        self.cash           = cash
        self._initial_cash  = cash
        self.order_book     = OrderBook()
        self.trade_book     = TradeBook()
        self.position_book  = PositionBook()
        self._db_path       = db_path
        self._last_prices:  dict[str, float] = {}

    # ------------------------------------------------------------------
    # Signal handler
    # ------------------------------------------------------------------

    def on_signal(
        self,
        signal: str,           # "BUY" | "SELL"
        symbol: str,
        price:  float,
        qty:    int = 1,
        slippage_pct: float = 0.0005,  # 0.05% default slippage
    ) -> Optional[str]:
        """Process a trading signal end-to-end.

        Flow: Signal → RiskCheck → OrderBook.place → OrderBook.fill
              → TradeBook.add → PositionBook.update → cash adjust

        Returns order_id on success, None on rejection.
        """
        side = OrderSide.BUY if signal.upper() == "BUY" else OrderSide.SELL

        # --- Risk check ---
        if side == OrderSide.BUY:
            required_cash = price * qty * (1 + slippage_pct)
            if required_cash > self.cash:
                log.warning(
                    f"[portfolio] REJECTED {symbol} BUY: "
                    f"need {required_cash:.0f}, have {self.cash:.0f}"
                )
                return None
        else:
            # Must have the position to sell
            pos = self.position_book.get(symbol)
            if pos is None or pos.quantity < qty:
                log.warning(
                    f"[portfolio] REJECTED {symbol} SELL: "
                    f"no/insufficient position (have {pos.quantity if pos else 0}, need {qty})"
                )
                return None

        # --- Place order ---
        order = Order(
            order_id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=qty,
        )
        order_id = self.order_book.place(order)

        # --- Simulate slippage ---
        exec_price = price * (1 + slippage_pct) if side == OrderSide.BUY else price * (1 - slippage_pct)
        exec_price = round(exec_price, 2)

        # --- Fill order ---
        filled_order = self.order_book.fill(order_id, exec_price)
        if filled_order is None:
            return None

        # --- Record trade ---
        trade = Trade(
            trade_id=str(uuid.uuid4()),
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=qty,
            price=exec_price,
            timestamp=datetime.now(),
        )

        # --- Update position and cash ---
        realized = self.position_book.update(trade)
        trade = Trade(
            trade_id=trade.trade_id,
            order_id=trade.order_id,
            symbol=trade.symbol,
            side=trade.side,
            quantity=trade.quantity,
            price=trade.price,
            realized_pnl=realized,
            timestamp=trade.timestamp,
        )
        self.trade_book.add(trade)

        if side == OrderSide.BUY:
            self.cash -= exec_price * qty
        else:
            self.cash += exec_price * qty

        self._last_prices[symbol] = exec_price
        log.info(
            f"[portfolio] {side.value} {symbol} x{qty} @ {exec_price:.2f} "
            f"| cash={self.cash:.0f}"
        )
        return order_id

    # ------------------------------------------------------------------
    # P&L
    # ------------------------------------------------------------------

    def daily_pnl(self) -> float:
        """Realized P&L from today's trades."""
        return sum(t.realized_pnl for t in self.trade_book.today())

    def total_pnl(self) -> float:
        """Realized + unrealized P&L."""
        return (
            self.trade_book.realized_pnl()
            + self.position_book.unrealized_pnl(self._last_prices)
        )

    def snapshot(self) -> PortfolioSnapshot:
        """Return a point-in-time portfolio snapshot."""
        unrealized = self.position_book.unrealized_pnl(self._last_prices)
        realized   = self.trade_book.realized_pnl()
        mkt_df     = self.position_book.mark_to_market(self._last_prices)
        positions_mv = (
            mkt_df["market_value"].sum() if not mkt_df.empty else 0.0
        )
        return PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            cash=round(self.cash, 2),
            open_positions=self.position_book.position_count(),
            unrealized_pnl=round(unrealized, 2),
            realized_pnl=round(realized, 2),
            total_value=round(self.cash + positions_mv, 2),
            daily_pnl=round(self.daily_pnl(), 2),
            total_trades=len(self.trade_book),
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist(self) -> None:
        """Save portfolio state to SQLite."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        cur  = conn.cursor()

        # --- trades table ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                order_id TEXT,
                symbol TEXT,
                side TEXT,
                quantity INTEGER,
                price REAL,
                realized_pnl REAL,
                timestamp TEXT,
                notes TEXT
            )
        """)
        for t in self.trade_book.all():
            cur.execute(
                "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    t.trade_id, t.order_id, t.symbol, t.side.value,
                    t.quantity, t.price, t.realized_pnl,
                    t.timestamp.isoformat(), t.notes,
                ),
            )

        # --- positions table ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                quantity INTEGER,
                avg_cost REAL,
                current_price REAL
            )
        """)
        cur.execute("DELETE FROM positions")
        for pos in self.position_book.all_open():
            cur.execute(
                "INSERT INTO positions VALUES (?,?,?,?)",
                (pos.symbol, pos.quantity, pos.avg_cost, pos.current_price),
            )

        # --- meta table ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute(
            "INSERT OR REPLACE INTO meta VALUES ('cash', ?)",
            (str(self.cash),),
        )
        cur.execute(
            "INSERT OR REPLACE INTO meta VALUES ('last_prices', ?)",
            (json.dumps(self._last_prices),),
        )

        conn.commit()
        conn.close()
        log.info(f"[portfolio] Persisted to {self._db_path}")

    def restore(self) -> bool:
        """Restore portfolio state from SQLite. Returns True if data found."""
        if not self._db_path.exists():
            log.info("[portfolio] No saved state found — starting fresh")
            return False

        conn = sqlite3.connect(self._db_path)
        cur  = conn.cursor()

        # --- Cash + prices ---
        try:
            cur.execute("SELECT value FROM meta WHERE key='cash'")
            row = cur.fetchone()
            if row:
                self.cash = float(row[0])
            cur.execute("SELECT value FROM meta WHERE key='last_prices'")
            row = cur.fetchone()
            if row:
                self._last_prices = json.loads(row[0])
        except Exception:
            pass

        # --- Trades ---
        try:
            cur.execute("SELECT * FROM trades")
            for row in cur.fetchall():
                trade = Trade(
                    trade_id=row[0], order_id=row[1], symbol=row[2],
                    side=OrderSide(row[3]), quantity=row[4],
                    price=row[5], realized_pnl=row[6],
                    timestamp=datetime.fromisoformat(row[7]), notes=row[8],
                )
                self.trade_book.add(trade)
        except Exception as exc:
            log.warning(f"[portfolio] restore trades: {exc}")

        # --- Positions ---
        try:
            cur.execute("SELECT * FROM positions")
            for row in cur.fetchall():
                from paper.models import Position
                pos = Position(
                    symbol=row[0], quantity=row[1],
                    avg_cost=row[2], current_price=row[3],
                )
                self.position_book._positions[pos.symbol] = pos
        except Exception as exc:
            log.warning(f"[portfolio] restore positions: {exc}")

        conn.close()
        log.info(
            f"[portfolio] Restored: cash={self.cash:.0f} "
            f"positions={self.position_book.position_count()} "
            f"trades={len(self.trade_book)}"
        )
        return True

    def __repr__(self) -> str:
        snap = self.snapshot()
        return (
            f"<PaperPortfolio cash={snap.cash:.0f} "
            f"positions={snap.open_positions} "
            f"total_value={snap.total_value:.0f} "
            f"pnl={snap.total_value - self._initial_cash:+.0f}>"
        )
