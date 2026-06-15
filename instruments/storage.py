"""Instruments SQLite storage — Phase 1.

WAL mode + single-transaction bulk inserts so a crash during refresh never
leaves a half-written instrument master.  A `schema_version` table records
the last successful refresh timestamp.

Two public classes
------------------
InstrumentStorage   — low-level, raw-dict API used directly by downloader.
InstrumentStore     — high-level, Instrument-object API used by search.py,
                      registry.py, and the rest of the codebase.

Both are exported so all existing imports keep working.

Tables:
    equity      — NSE equity master
    futures     — F&O futures instruments
    options     — F&O option instruments
    indices     — Index instruments
    schema_version — refresh timestamp + version

Indexes on: symbol, underlying, expiry, strike.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("instruments.storage")

DB_PATH = Path("eagle_base/data/instruments.db")

_SCHEMA_VERSION = "1.0.0"

# token and nse_symbol are included so Angel One broker token survives
# the DB round-trip. Previously missing from _COLS meant _to_dict() produced
# them but insert_bulk() silently dropped them, causing inst.token == '' on
# every resolved instrument and Angel One 400 Bad Request on every order.
_COLS = (
    "symbol", "name", "exchange", "segment",
    "isin", "lot_size", "tick_size",
    "expiry", "strike", "option_type",
    "underlying", "yf_symbol",
    "token", "nse_symbol",
)
_COLS_SQL     = ", ".join(f"{c} TEXT" for c in _COLS)
_PLACEHOLDERS = ", ".join("?" for _ in _COLS)

# Segment -> table mapping
_SEG_TABLE: dict[str, str] = {
    "EQ":  "equity",
    "FUT": "futures",
    "CE":  "options",
    "PE":  "options",
    "IDX": "indices",
}
_ALL_TABLES = ("equity", "futures", "options", "indices")


# ---------------------------------------------------------------------------
# InstrumentStorage — raw-dict / explicit-table API
# ---------------------------------------------------------------------------

class InstrumentStorage:
    """SQLite wrapper for the instrument master database (low-level API).

    All methods accept/return plain dicts.  Table name is always explicit.
    Used by InstrumentDownloader and direct DB work.
    """

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

            for table in _ALL_TABLES:
                conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({_COLS_SQL})")
                # Add token/nse_symbol columns to existing DBs that predate this fix
                for col in ("token", "nse_symbol"):
                    try:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
                    except sqlite3.OperationalError:
                        pass  # column already exists
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_symbol ON {table}(symbol)"
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_underlying ON {table}(underlying)"
                )
                if table in ("futures", "options"):
                    conn.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{table}_expiry ON {table}(expiry)"
                    )
                if table == "options":
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_options_strike ON options(strike)"
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
    # Atomic bulk insert
    # ------------------------------------------------------------------

    def insert_bulk(
        self,
        table: str,
        rows: list[dict[str, Any]],
        replace: bool = True,
    ) -> int:
        """Insert dicts into *table* atomically (WAL + BEGIN IMMEDIATE).

        Args:
            table  : 'equity' | 'futures' | 'options' | 'indices'
            rows   : list of dicts keyed by column name
            replace: DELETE existing rows first when True (full refresh)

        Returns number of rows inserted.
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

            tuples = [tuple(row.get(c) for c in _COLS) for row in rows]
            conn.executemany(f"INSERT INTO {table} VALUES ({_PLACEHOLDERS})", tuples)

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
    # Read operations (raw dict)
    # ------------------------------------------------------------------

    def search_raw(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Search all tables, return raw dicts (includes '_table' key)."""
        pattern = f"%{query.upper()}%"
        results: list[dict] = []
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            for table in _ALL_TABLES:
                try:
                    rows = conn.execute(
                        f"SELECT * FROM {table} "
                        f"WHERE UPPER(symbol) LIKE ? OR UPPER(name) LIKE ? LIMIT ?",
                        (pattern, pattern, limit),
                    ).fetchall()
                    for r in rows:
                        d = dict(r)
                        d["_table"] = table
                        results.append(d)
                except sqlite3.OperationalError:
                    pass  # table not yet created
        finally:
            conn.close()
        return results[:limit]

    # keep old name for downloader compatibility
    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.search_raw(query, limit)

    def get_by_symbol(self, symbol: str, table: str = "equity") -> Optional[dict]:
        """Exact-match lookup by symbol in a specific table (raw dict)."""
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


# ---------------------------------------------------------------------------
# InstrumentStore — Instrument-object API (used by search.py, registry.py)
# ---------------------------------------------------------------------------

class InstrumentStore(InstrumentStorage):
    """High-level wrapper around InstrumentStorage.

    Accepts and returns ``Instrument`` model objects instead of raw dicts.
    This is the class that InstrumentSearch, InstrumentRegistry, and all
    strategy/data components should use.

    insert_bulk(instruments)          — accepts list[Instrument], auto-routes to table
    search(query) -> list[Instrument]
    get_by_symbol(sym) -> Instrument | None
    list_by_segment(seg) -> list[Instrument]
    list_underlyings() -> list[str]
    count() -> dict[str, int]
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        super().__init__(db_path)
        self.init_db()  # ensure schema exists on first use

    # ------------------------------------------------------------------
    # Instrument <-> dict helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(inst) -> dict:
        """Convert an Instrument (dataclass/object) to a storage dict."""
        try:
            from dataclasses import asdict
            return asdict(inst)
        except Exception:
            return {c: getattr(inst, c, None) for c in _COLS}

    @staticmethod
    def _from_dict(d: dict):
        """Convert a raw storage dict to an Instrument object.

        token and nse_symbol are now explicitly passed so the Angel One
        broker token survives the full write -> read round-trip.
        """
        try:
            from instruments.models import Instrument
            return Instrument(
                symbol      = d.get("symbol", ""),
                name        = d.get("name", ""),
                exchange    = d.get("exchange", "NSE"),
                segment     = d.get("segment", "EQ"),
                isin        = d.get("isin"),
                lot_size    = int(d["lot_size"])    if d.get("lot_size")    else 1,
                tick_size   = float(d["tick_size"]) if d.get("tick_size")   else 0.05,
                expiry      = d.get("expiry"),
                strike      = float(d["strike"])    if d.get("strike")      else None,
                option_type = d.get("option_type"),
                underlying  = d.get("underlying"),
                yf_symbol   = d.get("yf_symbol"),
                token       = d.get("token", ""),
                nse_symbol  = d.get("nse_symbol", ""),
            )
        except Exception as exc:
            log.warning("[store] _from_dict failed: %s — returning raw dict", exc)
            return d

    @staticmethod
    def _table_for(inst) -> str:
        seg = (getattr(inst, "segment", None) or "EQ").upper()
        return _SEG_TABLE.get(seg, "equity")

    # ------------------------------------------------------------------
    # Instrument-level insert_bulk (overrides parent signature)
    # ------------------------------------------------------------------

    def insert_bulk(self, instruments, replace: bool = True) -> int:  # type: ignore[override]
        """Insert a list of Instrument objects.

        Auto-routes each instrument to the correct table based on segment.
        Groups by table and writes each group in one atomic transaction.

        Args:
            instruments : list[Instrument] — objects with a .segment attribute
            replace     : wipe each table before inserting (full refresh)

        Returns total rows inserted.
        """
        by_table: dict[str, list[dict]] = {t: [] for t in _ALL_TABLES}
        for inst in instruments:
            table = self._table_for(inst)
            by_table[table].append(self._to_dict(inst))

        total = 0
        for table, rows in by_table.items():
            if rows:
                total += super().insert_bulk(table, rows, replace=replace)
        return total

    # ------------------------------------------------------------------
    # Instrument-level search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 50):  # type: ignore[override]
        """Search all tables, return list[Instrument] ordered EQ->IDX->FUT->CE->PE."""
        raw = self.search_raw(query, limit)

        _order = {"equity": 0, "indices": 1, "futures": 2, "options": 3}
        raw.sort(key=lambda d: _order.get(d.get("_table", "equity"), 9))

        return [self._from_dict(d) for d in raw]

    # ------------------------------------------------------------------
    # Instrument-level get_by_symbol
    # ------------------------------------------------------------------

    def get_by_symbol(self, symbol: str, table: str = None):  # type: ignore[override]
        """Search all tables for an exact symbol match, return Instrument or None."""
        search_tables = [table] if table else list(_ALL_TABLES)
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            for tbl in search_tables:
                try:
                    row = conn.execute(
                        f"SELECT * FROM {tbl} WHERE symbol = ?", (symbol,)
                    ).fetchone()
                    if row:
                        return self._from_dict(dict(row))
                except sqlite3.OperationalError:
                    pass
        finally:
            conn.close()
        return None

    # ------------------------------------------------------------------
    # Segment listing
    # ------------------------------------------------------------------

    def list_by_segment(self, segment: str):
        """Return all Instrument objects for a given segment (EQ/FUT/CE/PE/IDX)."""
        table = _SEG_TABLE.get(segment.upper(), "equity")
        rows  = self.list_all(table)
        insts = [self._from_dict(r) for r in rows]
        if segment.upper() in ("CE", "PE"):
            insts = [i for i in insts if getattr(i, "option_type", None) == segment.upper()]
        return insts

    # ------------------------------------------------------------------
    # Underlyings
    # ------------------------------------------------------------------

    def list_underlyings(self) -> list[str]:
        """All distinct underlying symbols across futures + options tables."""
        results: list[str] = []
        conn = sqlite3.connect(str(self._db_path))
        try:
            for table in ("futures", "options"):
                try:
                    rows = conn.execute(
                        f"SELECT DISTINCT underlying FROM {table} "
                        f"WHERE underlying IS NOT NULL AND underlying != ''"
                    ).fetchall()
                    results.extend(r[0] for r in rows)
                except sqlite3.OperationalError:
                    pass
        finally:
            conn.close()
        seen: set[str] = set()
        unique = []
        for sym in results:
            if sym not in seen:
                seen.add(sym)
                unique.append(sym)
        return sorted(unique)

    # ------------------------------------------------------------------
    # Count
    # ------------------------------------------------------------------

    def count(self) -> dict[str, int]:
        """Return instrument count per segment: {EQ: N, FUT: N, CE: N, PE: N, IDX: N}."""
        conn = sqlite3.connect(str(self._db_path))
        counts: dict[str, int] = {"EQ": 0, "FUT": 0, "CE": 0, "PE": 0, "IDX": 0}
        try:
            for table, seg_key in [
                ("equity",  "EQ"),
                ("futures", "FUT"),
                ("indices", "IDX"),
            ]:
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    counts[seg_key] = row[0] if row else 0
                except sqlite3.OperationalError:
                    pass

            for seg in ("CE", "PE"):
                try:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM options WHERE option_type = ?", (seg,)
                    ).fetchone()
                    counts[seg] = row[0] if row else 0
                except sqlite3.OperationalError:
                    pass
        finally:
            conn.close()
        return counts

    def __repr__(self) -> str:
        return f"<InstrumentStore db={self._db_path} counts={self.count()}>"


# ---------------------------------------------------------------------------
# Convenience alias — some old code imports Storage directly
# ---------------------------------------------------------------------------
Storage = InstrumentStore
