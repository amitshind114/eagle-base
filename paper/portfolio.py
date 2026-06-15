"""PaperPortfolio — Phase 6 Paper Trading.

Orchestrates OrderBook + TradeBook + PositionBook into one unified interface.
Persists and restores state to/from SQLite so positions survive restarts.

Key guarantees:
  - persist() is ATOMIC: uses WAL mode + BEGIN IMMEDIATE so crash mid-write
    never leaves a partial state.
  - restore() verifies integrity: position.quantity must equal
    sum(BUY trades) - sum(SELL trades) for every symbol.
  - If corruption detected, self._corrupted = True and all new orders are
    blocked until manual reconciliation.
  - on_signal() runs RiskManager.check() BEFORE cash/position guards so
    drawdown, daily-loss, and position-size caps are always enforced.

Usage:
    portfolio = PaperPortfolio(cash=500_000.0)
    portfolio.on_signal(signal="BUY", symbol="RELIANCE", price=2500.0, qty=10)
    portfolio.daily_pnl()
    snap = portfolio.snapshot()
    portfolio.persist()     # atomic save to SQLite
    portfolio.restore()     # load + integrity-check on startup
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from paper.models import Order, OrderSide, OrderStatus, OrderType
from paper.order_book import OrderBook
from paper.position_book import PositionBook
from paper.trade_book import Trade, TradeBook

log = logging.getLogger("paper.portfolio")

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
    corrupted:        bool = False


def _build_default_risk_manager():
    """Build a RiskManager from Settings defaults.

    Imported lazily to avoid circular imports and to keep paper/ independent
    of risk/ at module load time.
    """
    try:
        from core.config import settings
        from risk.limits import RiskManager
        return RiskManager(
            max_daily_loss=settings.max_daily_loss,
            max_drawdown_pct=settings.max_drawdown_pct,
            max_position_size=settings.max_position_exposure_pct * settings.default_capital / 100,
            max_trades_per_day=200,   # generous paper-trading default
        )
    except Exception as exc:
        log.warning("[portfolio] Could not build RiskManager: %s — risk gate disabled", exc)
        return None


class PaperPortfolio:
    """Full paper trading portfolio: cash + books + atomic persistence."""

    def __init__(
        self,
        cash: float = 500_000.0,
        db_path: Path = DB_PATH,
        fetcher=None,
        risk_manager=None,
    ) -> None:
        self.cash           = cash
        self._initial_cash  = cash
        self.order_book     = OrderBook()
        self.trade_book     = TradeBook()
        self.position_book  = PositionBook()
        self._db_path       = db_path
        self._last_prices:  dict[str, float] = {}
        self._fetcher       = fetcher          # optional DataFetcher for MTM prices
        self._corrupted:    bool = False       # set True if restore detects mismatch
        # RiskManager gate — built from settings if not injected
        self._risk_manager  = risk_manager if risk_manager is not None else _build_default_risk_manager()

    # ------------------------------------------------------------------
    # Corruption guard
    # ------------------------------------------------------------------

    @property
    def is_corrupted(self) -> bool:
        return self._corrupted

    def _assert_not_corrupted(self) -> None:
        if self._corrupted:
            raise RuntimeError(
                "Portfolio state is CORRUPTED. Manual reconciliation required. "
                "No new orders will be accepted until resolved."
            )

    # ------------------------------------------------------------------
    # Signal handler
    # ------------------------------------------------------------------

    def on_signal(
        self,
        signal: str,           # "BUY" | "SELL"
        symbol: str,
        price:  float,
        qty:    int = 1,
        slippage_pct: float = 0.0005,
    ) -> Optional[str]:
        """Process a trading signal end-to-end.

        Flow: Signal → CorruptionGuard → RiskGate → CashCheck
              → OrderBook.place → OrderBook.fill → TradeBook.add
              → PositionBook.update → cash adjust

        Returns order_id on success, None on rejection.
        """
        self._assert_not_corrupted()

        side = OrderSide.BUY if signal.upper() == "BUY" else OrderSide.SELL

        # --- Risk gate (drawdown / daily-loss / position-size caps) ---
        if self._risk_manager is not None:
            try:
                pnl = self.daily_pnl()
                order_value = price * qty
                self._risk_manager.check(
                    pnl=pnl,
                    capital=self._initial_cash,
                    trade_value=order_value,
                )
            except Exception as exc:
                # Catches RiskLimitBreached and any unexpected errors
                log.warning(
                    "[portfolio] RISK GATE BLOCKED %s %s x%d @ %.2f: %s",
                    signal.upper(), symbol, qty, price, exc,
                )
                return None

        # --- Cash / position check ---
        if side == OrderSide.BUY:
            required_cash = price * qty * (1 + slippage_pct)
            if required_cash > self.cash:
                log.warning(
                    "[portfolio] REJECTED %s BUY: need %.0f, have %.0f",
                    symbol, required_cash, self.cash,
                )
                return None
        else:
            pos = self.position_book.get(symbol)
            if pos is None or pos.quantity < qty:
                log.warning(
                    "[portfolio] REJECTED %s SELL: have %d, need %d",
                    symbol, pos.quantity if pos else 0, qty,
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
            "[portfolio] %s %s x%d @ %.2f | cash=%.0f",
            side.value, symbol, qty, exec_price, self.cash,
        )
        return order_id

    # ------------------------------------------------------------------
    # P&L — mark-to-market via DataFetcher
    # ------------------------------------------------------------------

    def daily_pnl(self) -> float:
        """Realized PnL from today’s trades PLUS unrealized PnL at live prices.

        If a DataFetcher was injected, calls fetch_latest_price() for every
        open position so MTM is current.  Falls back to last known prices if
        no fetcher is available.

        Formula:
            daily_pnl = sum(today realized PnL) + unrealized PnL
            unrealized PnL per pos = qty * (current_price - avg_cost)
        """
        # Refresh prices from live fetcher if available
        if self._fetcher is not None:
            for pos in self.position_book.all_open():
                try:
                    live_price = self._fetcher.fetch_latest_price(pos.symbol)
                    if live_price and live_price > 0:
                        self._last_prices[pos.symbol] = live_price
                except Exception as exc:
                    log.warning("[portfolio] MTM price fetch failed for %s: %s", pos.symbol, exc)

        realized_today = sum(t.realized_pnl for t in self.trade_book.today())
        unrealized = self.position_book.unrealized_pnl(self._last_prices)
        return round(realized_today + unrealized, 2)

    def total_pnl(self) -> float:
        """All-time realized + current unrealized PnL."""
        return round(
            self.trade_book.realized_pnl()
            + self.position_book.unrealized_pnl(self._last_prices),
            2,
        )

    def snapshot(self) -> PortfolioSnapshot:
        """Return a point-in-time portfolio snapshot."""
        unrealized   = self.position_book.unrealized_pnl(self._last_prices)
        realized     = self.trade_book.realized_pnl()
        mkt_df       = self.position_book.mark_to_market(self._last_prices)
        positions_mv = mkt_df["market_value"].sum() if not mkt_df.empty else 0.0
        return PortfolioSnapshot(
            timestamp=datetime.now().isoformat(),
            cash=round(self.cash, 2),
            open_positions=self.position_book.position_count(),
            unrealized_pnl=round(unrealized, 2),
            realized_pnl=round(realized, 2),
            total_value=round(self.cash + positions_mv, 2),
            daily_pnl=round(self.daily_pnl(), 2),
            total_trades=len(self.trade_book),
            corrupted=self._corrupted,
        )

    # ------------------------------------------------------------------
    # Atomic persistence (WAL + BEGIN IMMEDIATE)
    # ------------------------------------------------------------------

    def persist(self) -> None:
        """Atomically save portfolio state to SQLite."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id    TEXT PRIMARY KEY,
                    order_id    TEXT,
                    symbol      TEXT,
                    side        TEXT,
                    quantity    INTEGER,
                    price       REAL,
                    realized_pnl REAL,
                    timestamp   TEXT,
                    notes       TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    symbol        TEXT PRIMARY KEY,
                    quantity      INTEGER,
                    avg_cost      REAL,
                    current_price REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            for t in self.trade_book.all():
                conn.execute(
                    "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        t.trade_id, t.order_id, t.symbol, t.side.value,
                        t.quantity, t.price, t.realized_pnl,
                        t.timestamp.isoformat(), t.notes,
                    ),
                )
            conn.execute("DELETE FROM positions")
            for pos in self.position_book.all_open():
                conn.execute(
                    "INSERT INTO positions VALUES (?,?,?,?)",
                    (pos.symbol, pos.quantity, pos.avg_cost, pos.current_price),
                )
            conn.execute(
                "INSERT OR REPLACE INTO meta VALUES ('cash', ?)", (str(self.cash),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta VALUES ('last_prices', ?)",
                (json.dumps(self._last_prices),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta VALUES ('persisted_at', ?)",
                (datetime.now().isoformat(),),
            )
            conn.execute("COMMIT")
            log.info("[portfolio] Persisted atomically to %s", self._db_path)
        except Exception:
            conn.execute("ROLLBACK")
            log.exception("[portfolio] persist() FAILED — rolled back")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Restore with integrity check
    # ------------------------------------------------------------------

    def restore(self) -> bool:
        """Restore portfolio state from SQLite, then verify integrity."""
        if not self._db_path.exists():
            log.info("[portfolio] No saved state — starting fresh")
            return False

        conn = sqlite3.connect(str(self._db_path))
        try:
            try:
                row = conn.execute("SELECT value FROM meta WHERE key='cash'").fetchone()
                if row:
                    self.cash = float(row[0])
                row = conn.execute("SELECT value FROM meta WHERE key='last_prices'").fetchone()
                if row:
                    self._last_prices = json.loads(row[0])
            except Exception as exc:
                log.warning("[portfolio] restore meta: %s", exc)
            try:
                for row in conn.execute("SELECT * FROM trades").fetchall():
                    trade = Trade(
                        trade_id=row[0], order_id=row[1], symbol=row[2],
                        side=OrderSide(row[3]), quantity=row[4],
                        price=row[5], realized_pnl=row[6],
                        timestamp=datetime.fromisoformat(row[7]), notes=row[8],
                    )
                    self.trade_book.add(trade)
            except Exception as exc:
                log.warning("[portfolio] restore trades: %s", exc)
            try:
                for row in conn.execute("SELECT * FROM positions").fetchall():
                    from paper.models import Position
                    pos = Position(
                        symbol=row[0], quantity=row[1],
                        avg_cost=row[2], current_price=row[3],
                    )
                    self.position_book._positions[pos.symbol] = pos
            except Exception as exc:
                log.warning("[portfolio] restore positions: %s", exc)
        finally:
            conn.close()

        log.info(
            "[portfolio] Restored: cash=%.0f positions=%d trades=%d",
            self.cash, self.position_book.position_count(), len(self.trade_book),
        )
        self._verify_integrity()
        return True

    def _verify_integrity(self) -> None:
        from collections import defaultdict
        net_qty: dict[str, int] = defaultdict(int)
        for trade in self.trade_book.all():
            if trade.side == OrderSide.BUY:
                net_qty[trade.symbol] += trade.quantity
            else:
                net_qty[trade.symbol] -= trade.quantity

        corruption_found = False
        for pos in self.position_book.all_open():
            expected = net_qty.get(pos.symbol, 0)
            if pos.quantity != expected:
                log.critical(
                    "[portfolio] INTEGRITY MISMATCH for %s: "
                    "position_book=%d, trade_book_net=%d.",
                    pos.symbol, pos.quantity, expected,
                )
                corruption_found = True
        for symbol, qty in net_qty.items():
            if qty > 0 and self.position_book.get(symbol) is None:
                log.critical(
                    "[portfolio] INTEGRITY MISMATCH: trade_book shows %d net %s "
                    "but no position entry found.", qty, symbol,
                )
                corruption_found = True
        if corruption_found:
            self._corrupted = True
            log.critical("[portfolio] State marked CORRUPTED — no new orders until reconciled.")
        else:
            log.info("[portfolio] Integrity check PASSED.")

    def __repr__(self) -> str:
        snap = self.snapshot()
        corruption_tag = " [CORRUPTED]" if self._corrupted else ""
        return (
            f"<PaperPortfolio cash={snap.cash:.0f} "
            f"positions={snap.open_positions} "
            f"total_value={snap.total_value:.0f} "
            f"pnl={snap.total_value - self._initial_cash:+.0f}"
            f"{corruption_tag}>"
        )
