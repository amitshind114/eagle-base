"""Append-only audit trail for every system decision.

Writes one JSON line per event to ~/.eagle/audit.jsonl.
Never raises — if the file can\'t be written, logs a warning and continues.
Safe to call from anywhere: strategies, risk gate, paper broker, live executor.

Usage:
    from core.audit import audit

    audit.record("SIGNAL",        "RELIANCE", session="paper",  direction="BUY",  confidence=0.82)
    audit.record("GATE_BLOCK",    "INFY",     session="live",   reason="Max trades reached")
    audit.record("ORDER_FILLED",  "TCS",      session="paper",  side="BUY", qty=5, price=3900.0)
    audit.record("ORDER_BLOCKED", "HDFC",     session="paper",  reason="Insufficient capital")
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.logger import get_logger

log = get_logger("core.audit")
IST = ZoneInfo("Asia/Kolkata")

_DEFAULT_PATH = Path.home() / ".eagle" / "audit.jsonl"


class AuditLog:
    """Thread-safe append-only audit trail."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_PATH
        self._lock = threading.Lock()
        self._ensure_dir()

    def record(self, event: str, symbol: str, session: str = "", **kwargs: Any) -> None:
        """Append one audit record.  Never raises.

        event:   e.g. "SIGNAL", "GATE_BLOCK", "ORDER_FILLED", "ORDER_REJECTED"
        symbol:  trading symbol
        session: "paper", "live", "backtest"
        kwargs:  any additional fields (reason, side, qty, price, pnl, flags, …)
        """
        record = {
            "ts":      datetime.now(tz=IST).isoformat(timespec="seconds"),
            "event":   event,
            "symbol":  symbol.upper(),
            "session": session,
            **{k: v for k, v in kwargs.items() if v is not None},
        }
        try:
            with self._lock:
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:
            log.warning(f"[audit] Write failed: {exc}")

    def tail(self, n: int = 50) -> list[dict]:
        """Return the last `n` audit records as dicts (newest last)."""
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
            return [json.loads(line) for line in lines[-n:]]
        except Exception:
            return []

    def today(self, session: str | None = None) -> list[dict]:
        """Return all records for today\'s date, optionally filtered by session."""
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
