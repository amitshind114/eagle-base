"""SQLite connection pool for Eagle.

Prevents every module from opening a separate SQLite connection.
All DB access across instruments, paper, audit, and risk modules
should use get_conn() instead of sqlite3.connect() directly.

Pattern:
    from core.db import get_conn

    with get_conn(DB_PATH) as conn:
        conn.execute("SELECT ...")
        conn.commit()

Pool semantics:
  - One persistent connection per db_path (check_same_thread=False).
  - One threading.Lock per connection — callers take it via context manager.
  - WAL mode + NORMAL sync enabled on first connect.
  - If a connection goes stale (OperationalError), it is dropped and
    re-opened transparently.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from core.logger import get_logger

log = get_logger("core.db")

__all__ = ["get_conn", "close_all"]

# ── Internal pool state ───────────────────────────────────────────────────────
# { db_path_str: (connection, lock) }
_pool: dict[str, tuple[sqlite3.Connection, threading.Lock]] = {}
_pool_lock = threading.Lock()   # guards mutations to _pool dict


def _open(path_str: str) -> sqlite3.Connection:
    """Open a new WAL-mode connection."""
    conn = sqlite3.connect(path_str, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA cache_size=-8192")   # 8 MB page cache
    log.debug(f"[db] Opened connection to {path_str}")
    return conn


def _get_or_create(path_str: str) -> tuple[sqlite3.Connection, threading.Lock]:
    with _pool_lock:
        if path_str not in _pool:
            conn = _open(path_str)
            lock = threading.Lock()
            _pool[path_str] = (conn, lock)
        return _pool[path_str]


@contextmanager
def get_conn(db_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a pooled, locked SQLite connection.

    Usage:
        with get_conn("~/.eagle/paper.db") as conn:
            rows = conn.execute("SELECT * FROM orders").fetchall()

    The lock is released when the `with` block exits.
    If the connection is stale it is transparently replaced.
    """
    path_str = str(db_path)
    conn, lock = _get_or_create(path_str)

    with lock:
        # Health check — try a cheap no-op; replace on failure
        try:
            conn.execute("SELECT 1")
        except sqlite3.OperationalError:
            log.warning(f"[db] Stale connection for {path_str} — reopening.")
            try:
                conn.close()
            except Exception:
                pass
            conn = _open(path_str)
            with _pool_lock:
                lock2 = threading.Lock()
                _pool[path_str] = (conn, lock2)
            # Re-acquire new lock for this call
            with lock2:
                yield conn
            return
        yield conn


def close_all() -> None:
    """Close every pooled connection. Call at process shutdown."""
    with _pool_lock:
        for path_str, (conn, _) in list(_pool.items()):
            try:
                conn.close()
                log.debug(f"[db] Closed connection to {path_str}")
            except Exception:
                pass
        _pool.clear()
