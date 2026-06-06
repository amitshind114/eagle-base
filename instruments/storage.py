"""Instruments SQLite storage — Phase 1.

WAL mode + single-transaction bulk inserts so a crash during refresh never
leaves a half-written instrument master.  A `schema_version` table records
the last successful refresh timestamp.

Tables:
    equity      — NSE equity master
    futures     — F&O futures instruments
    options     — F&O option instruments
    indices     — Index instruments
    schema_version — refresh timestamp + version

Indexes on: symbol, underlying, expiry, strike for fast look-up.

Usage:
    storage = InstrumentStorage()
    storage.init_db()
    storage.insert_bulk("equity", rows)          # atomic
    results = storage.search("RELIANCE")
    inst = storage.get_by_symbol("RELIANCE-EQ")
    print(storage.last_refresh())                # ISO timestamp or None
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("instruments.storage")

DB_PATH = Path("eagle_base/data/instruments.db")

_SCHEMA_VERSION = "1.0.0"

# Shared column list for all segment tables
_COLS = (
    "symbol", "name", "exchange", "segment",
    "isin", "lot_size", "tick_size",
    "expiry", "strike", "option_type",
    "underlying", "yf_symbol",
)
_COLS_SQL = ", ".join(f"{c} TEXT" for c in _COLS)
_PLACEHOLDERS = ", ".join("?" for _ in _COLS)


class InstrumentStorage:
    """SQLite wrapper for the instrument master database."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Schema init
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            for table in ("equity", "futures", "options", "indices"):
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ({_COLS_SQL})"
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_symbol "
                    f"ON {table}(symbol)"
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_underlying "
                    f"ON {table}(underlying)"
                )
                if table in ("futures", "options"):
                    conn.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{table}_expiry "
                        f"ON {table}(expiry)"
                    )
                if table == "options":
                    conn.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_options_strike "
                        f"ON options(strike)"
                    )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version       TEXT,
                    last_refresh  TEXT
                )
            """)
            conn.commit()
            log.info("[storage] DB initialised at %s", self._db_path)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Atomic bulk insert (WAL + BEGIN IMMEDIATE)
    # ------------------------------------------------------------------

    def insert_bulk(
        self,
        table: str,
        rows: list[dict[str, Any]],
        replace: bool = True,
    ) -> int:
        """Insert rows into *table* inside a single atomic transaction.

        Uses BEGIN IMMEDIATE so concurrent readers can still proceed (WAL)
        but no second writer can interleave.  On any exception the whole
        batch is rolled back — the old data remains intact.

        Args:
            table  : One of 'equity', 'futures', 'options', 'indices'.
            rows   : List of dicts keyed by column name.
            replace: If True, DELETE existing rows first (full refresh).

        Returns:
            Number of rows inserted.
        """
        if not rows:
            return 0

        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            conn.execute("BEGIN IMMEDIATE")

            if replace:
                conn.execute(f"DELETE FROM {table}")

            tuples = [
                tuple(row.get(c, None) for c in _COLS)
                for row in rows
            ]
            conn.executemany(
                f"INSERT INTO {table} VALUES ({_PLACEHOLDERS})",
                tuples,
            )

            # Update refresh timestamp
            conn.execute("DELETE FROM schema_version")
            conn.execute(
                "INSERT INTO schema_version VALUES (?, ?)",
                (_SCHEMA_VERSION, datetime.now().isoformat()),
            )

            conn.execute("COMMIT")
            log.info("[storage] Inserted %d rows into '%s'", len(rows), table)
            return len(rows)

        except Exception:
            conn.execute("ROLLBACK")
            log.exception("[storage] insert_bulk FAILED for '%s' — rolled back", table)
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Full-text search across all four tables by symbol or name prefix."""
        pattern = f"%{query.upper()}%"
        results: list[dict] = []
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            for table in ("equity", "futures", "options", "indices"):
                rows = conn.execute(
                    f"SELECT * FROM {table} "
                    f"WHERE UPPER(symbol) LIKE ? OR UPPER(name) LIKE ? "
                    f"LIMIT ?",
                    (pattern, pattern, limit),
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    d["_table"] = table
                    results.append(d)
        finally:
            conn.close()
        return results[:limit]

    def get_by_symbol(self, symbol: str, table: str = "equity") -> Optional[dict]:
        """Exact-match lookup by symbol in a specific table."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE symbol = ?", (symbol,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_all(self, table: str) -> list[dict]:
        """Return all rows from a table."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Version / refresh timestamp
    # ------------------------------------------------------------------

    def last_refresh(self) -> Optional[str]:
        """Return ISO timestamp of last successful refresh, or None."""
        if not self._db_path.exists():
            return None
        conn = sqlite3.connect(str(self._db_path))
        try:
            row = conn.execute(
                "SELECT last_refresh FROM schema_version ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
        except Exception:
            return None
        finally:
            conn.close()

    def schema_version(self) -> Optional[str]:
        """Return the schema version string."""
        if not self._db_path.exists():
            return None
        conn = sqlite3.connect(str(self._db_path))
        try:
            row = conn.execute(
                "SELECT version FROM schema_version ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
        except Exception:
            return None
        finally:
            conn.close()

    def __repr__(self) -> str:
        return f"<InstrumentStorage db={self._db_path} last_refresh={self.last_refresh()}>"
