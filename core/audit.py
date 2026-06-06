"""Append-only audit trail for every system decision.

Writes one JSON line per event to ~/.eagle/audit.jsonl.
Never raises — if the file can't be written, logs a warning and continues.
Safe to call from anywhere: strategies, risk gate, paper broker, live executor.

Usage:
    from core.audit import audit

    audit.record("SIGNAL",        "RELIANCE", session="paper",  direction="BUY",  confidence=0.82)
    audit.record("GATE_BLOCK",    "INFY",     session="live",   reason="Max trades reached")
    audit.record("ORDER_FILLED",  "TCS",      session="paper",  side="BUY", qty=5, price=3900.0)
    audit.record("ORDER_BLOCKED", "HDFC",     session="paper",  reason="Insufficient capital")
    audit.daily_summary(session="live", total_trades=4, total_pnl=320.0)
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.logger import get_logger

log = get_logger("core.audit")
IST = ZoneInfo("Asia/Kolkata")

_DEFAULT_PATH     = Path.home() / ".eagle" / "audit.jsonl"
_MAX_BYTES        = 10 * 1024 * 1024   # 10 MB per file
_BACKUP_COUNT     = 7                  # keep 7 rotated files (70 MB total)


class AuditLog:
    """Thread-safe append-only audit trail with log rotation.

    Files rotate at 10 MB, keeping 7 backups:
        audit.jsonl          ← current
        audit.jsonl.1        ← previous
        ...
        audit.jsonl.7        ← oldest
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_PATH
        self._lock = threading.Lock()
        self._ensure_dir()
        self._handler = self._make_handler()

    # ── Rotation setup ─────────────────────────────────────────────────────

    def _make_handler(self) -> logging.handlers.RotatingFileHandler:
        """Create a RotatingFileHandler for the audit log."""
        try:
            handler = logging.handlers.RotatingFileHandler(
                filename    = str(self._path),
                maxBytes    = _MAX_BYTES,
                backupCount = _BACKUP_COUNT,
                encoding    = "utf-8",
            )
            # Plain formatter — we write raw JSON lines ourselves
            handler.setFormatter(logging.Formatter("%(message)s"))
            handler.setLevel(logging.DEBUG)
            return handler
        except Exception as exc:
            log.warning(f"[audit] Could not create RotatingFileHandler: {exc}")
            return None  # type: ignore[return-value]

    # ── Core write ────────────────────────────────────────────────────────────

    def _write(self, line: str) -> None:
        """Write one JSON line via the rotating handler (thread-safe)."""
        with self._lock:
            if self._handler:
                # Emit through the rotating handler so rotation is handled
                record = logging.LogRecord(
                    name="audit", level=logging.INFO,
                    pathname="", lineno=0,
                    msg=line, args=(), exc_info=None,
                )
                try:
                    self._handler.emit(record)
                except Exception:
                    # Last-resort: plain append
                    try:
                        with self._path.open("a", encoding="utf-8") as f:
                            f.write(line + "\n")
                    except Exception as exc2:
                        log.warning(f"[audit] Write failed (fallback): {exc2}")
            else:
                # No handler — plain append
                try:
                    with self._path.open("a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except Exception as exc:
                    log.warning(f"[audit] Write failed: {exc}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def record(self, event: str, symbol: str, session: str = "", **kwargs: Any) -> None:
        """Append one audit record. Never raises.

        event:   e.g. "SIGNAL", "GATE_BLOCK", "ORDER_FILLED", "ORDER_REJECTED"
        symbol:  trading symbol
        session: "paper", "live", "backtest"
        kwargs:  any additional fields (reason, side, qty, price, pnl, flags, …)
        """
        entry = {
            "ts":      datetime.now(tz=IST).isoformat(timespec="seconds"),
            "event":   event,
            "symbol":  symbol.upper(),
            "session": session,
            **{k: v for k, v in kwargs.items() if v is not None},
        }
        try:
            line = json.dumps(entry, default=str)
        except Exception as exc:
            log.warning(f"[audit] JSON serialisation failed: {exc}")
            return
        self._write(line)

    def daily_summary(
        self,
        session: str = "live",
        total_trades: int = 0,
        total_pnl: float = 0.0,
        max_position_value: float = 0.0,
        reconcile_discrepancies: int = 0,
        **kwargs: Any,
    ) -> None:
        """Write a structured daily summary entry at session end.

        Called by post_market_report() at 15:35 each trading day.
        Used by the monitor dashboard for day-end stats.
        """
        self.record(
            "DAILY_SUMMARY",
            "SYSTEM",
            session=session,
            total_trades=total_trades,
            total_pnl=round(total_pnl, 2),
            max_position_value=round(max_position_value, 2),
            reconcile_discrepancies=reconcile_discrepancies,
            **kwargs,
        )
        log.info(
            f"[audit] Daily summary — trades={total_trades} "
            f"pnl={total_pnl:.2f} max_pos={max_position_value:.2f} "
            f"discrepancies={reconcile_discrepancies}"
        )

    # ── Read helpers ────────────────────────────────────────────────────────────

    def tail(self, n: int = 50) -> list[dict]:
        """Return the last `n` audit records as dicts (newest last)."""
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
            return [json.loads(line) for line in lines[-n:]]
        except Exception:
            return []

    def today(self, session: str | None = None) -> list[dict]:
        """Return all records for today's date, optionally filtered by session."""
        today_str = datetime.now(tz=IST).strftime("%Y-%m-%d")
        try:
            lines  = self._path.read_text(encoding="utf-8").strip().splitlines()
            events = [json.loads(l) for l in lines if today_str in l]
            if session:
                events = [e for e in events if e.get("session") == session]
            return events
        except Exception:
            return []

    def _ensure_dir(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.warning(f"[audit] Cannot create audit dir: {exc}")


# Module-level singleton
audit = AuditLog()
