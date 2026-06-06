"""SQLite storage for instrument master — Phase 1.

Tables:
  equity   — all NSE equity instruments
  futures  — F&O futures
  options  — F&O options (CE/PE)
  indices  — index instruments

Usage:
    from instruments.storage import InstrumentStore
    store = InstrumentStore()
    store.insert_bulk(instruments)
    results = store.search("RELIANCE")
    inst    = store.get_by_symbol("RELIANCE-EQ")
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional

from core.logger import get_logger
from .models import Instrument

log = get_logger("instruments.storage")

_DB_PATH = Path("eagle_base/data/instruments.db")

_DDL = """
CREATE TABLE IF NOT EXISTS instruments (
    symbol      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    exchange    TEXT NOT NULL DEFAULT 'NSE',
    segment     TEXT NOT NULL DEFAULT 'EQ',
    isin        TEXT DEFAULT '',
    lot_size    INTEGER DEFAULT 1,
    tick_size   REAL DEFAULT 0.05,
    sector      TEXT DEFAULT '',
    industry    TEXT DEFAULT '',
    underlying  TEXT DEFAULT '',
    expiry      TEXT DEFAULT '',
    strike      REAL DEFAULT 0,
    option_type TEXT DEFAULT '',
    yf_symbol   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_underlying ON instruments(underlying);
CREATE INDEX IF NOT EXISTS idx_segment    ON instruments(segment);
CREATE INDEX IF NOT EXISTS idx_name       ON instruments(name COLLATE NOCASE);
"""


class InstrumentStore:
    """SQLite-backed instrument master store."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Write ─────────────────────────────────────────────────────────────

    def insert_bulk(self, instruments: List[Instrument]) -> int:
        """Upsert a list of instruments. Returns count inserted/updated."""
        rows = [self._to_row(i) for i in instruments]
        with self._conn() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO instruments
                (symbol, name, exchange, segment, isin, lot_size, tick_size,
                 sector, industry, underlying, expiry, strike, option_type, yf_symbol)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
        log.info(f"Upserted {len(rows)} instruments.")
        return len(rows)

    def clear(self, segment: Optional[str] = None) -> None:
        """Clear all or segment-specific instruments."""
        with self._conn() as conn:
            if segment:
                conn.execute("DELETE FROM instruments WHERE segment=?", (segment,))
            else:
                conn.execute("DELETE FROM instruments")

    # ── Read ──────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 50) -> List[Instrument]:
        """Full-text search across symbol, name, underlying."""
        q = f"%{query.upper()}%"
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM instruments
                WHERE UPPER(symbol) LIKE ?
                   OR UPPER(name)   LIKE ?
                   OR UPPER(underlying) LIKE ?
                ORDER BY
                    CASE segment
                        WHEN 'EQ'  THEN 1
                        WHEN 'IDX' THEN 2
                        WHEN 'FUT' THEN 3
                        WHEN 'CE'  THEN 4
                        WHEN 'PE'  THEN 5
                        ELSE 6
                    END
                LIMIT ?
                """,
                (q, q, q, limit),
            ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_by_symbol(self, symbol: str) -> Optional[Instrument]:
        """Exact symbol lookup."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM instruments WHERE UPPER(symbol)=?",
                (symbol.upper(),),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_by_segment(self, segment: str) -> List[Instrument]:
        """All instruments for a segment: EQ, FUT, CE, PE, IDX."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM instruments WHERE segment=? ORDER BY symbol",
                (segment.upper(),),
            ).fetchall()
        return [self._from_row(r) for r in rows]

    def list_all(self, exchange: Optional[str] = None) -> List[Instrument]:
        """Return all instruments, optionally filtered by exchange."""
        with self._conn() as conn:
            if exchange:
                rows = conn.execute(
                    "SELECT * FROM instruments WHERE UPPER(exchange)=? ORDER BY symbol",
                    (exchange.upper(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM instruments ORDER BY symbol"
                ).fetchall()
        return [self._from_row(r) for r in rows]

    def list_underlyings(self) -> List[str]:
        """All unique underlying symbols (stocks with F&O)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT underlying FROM instruments WHERE underlying != '' ORDER BY underlying"
            ).fetchall()
        return [r[0] for r in rows]

    def count(self) -> int:
        """Total count of instruments in the store."""
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()
        return int(row[0])

    def count_by_segment(self) -> dict[str, int]:
        """Count of instruments per segment."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT segment, COUNT(*) FROM instruments GROUP BY segment"
            ).fetchall()
        return dict(rows)

    # ── Internals ─────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _to_row(i: Instrument) -> tuple:
        return (
            i.symbol, i.name, i.exchange, i.segment, i.isin,
            i.lot_size, i.tick_size, i.sector, i.industry,
            i.underlying or "",
            i.expiry.isoformat() if i.expiry else "",
            i.strike or 0.0,
            i.option_type or "",
            i.yf_symbol,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Instrument:
        from datetime import date
        expiry = None
        if row["expiry"]:
            try:
                expiry = date.fromisoformat(row["expiry"])
            except ValueError:
                expiry = None
        return Instrument(
            symbol=row["symbol"],
            name=row["name"],
            exchange=row["exchange"],
            segment=row["segment"],
            isin=row["isin"],
            lot_size=row["lot_size"],
            tick_size=row["tick_size"],
            sector=row["sector"],
            industry=row["industry"],
            underlying=row["underlying"] or None,
            expiry=expiry,
            strike=row["strike"] or None,
            option_type=row["option_type"] or None,
            yf_symbol=row["yf_symbol"],
        )
