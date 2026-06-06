"""Instrument token map — equity + F&O.

Maps human-readable symbols to Angel One token IDs for live order placement.

Coverage:
    NSE Equity  : {"RELIANCE": "2885", "INFY": "1594", ...}
    NSE F&O     : {"NIFTY24DEC21500CE": "tokenid", ...}

Expiry helpers:
    get_near_expiry(symbol)  → nearest weekly/monthly expiry date string
    get_all_expiries(symbol) → sorted list of all available expiry dates

Usage:
    from instruments.token_map import get_token, get_near_expiry

    token = get_token("RELIANCE")          # "2885"
    token = get_token("NIFTY24DEC21500CE") # F&O token
    expiry = get_near_expiry("NIFTY")      # "2026-07-03"
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from core.logger import get_logger

log = get_logger("instruments.token_map")

__all__ = [
    "get_token",
    "get_exchange",
    "get_near_expiry",
    "get_all_expiries",
    "refresh_from_db",
    "TokenMap",
]


# ════════════════════════════════════════════════════════════════════════════
# TokenMap class
# ════════════════════════════════════════════════════════════════════════════

class TokenMap:
    """In-memory token map loaded from instruments SQLite DB.

    Loads both NSE equity AND NSE F&O (NFO) tokens in one pass.
    Re-loadable at any time by calling .refresh().
    """

    def __init__(self) -> None:
        # { symbol_upper: {"token": str, "exchange": str, "expiry": str|None, ...} }
        self._map: dict[str, dict] = {}
        self._loaded = False

    # ── Load / refresh ────────────────────────────────────────────────────

    def refresh(self, db_path: Path | None = None) -> int:
        """Reload from instruments SQLite DB. Returns number of tokens loaded."""
        try:
            from instruments.storage import InstrumentStore, DB_PATH
            store = InstrumentStore(db_path or DB_PATH)

            new_map: dict[str, dict] = {}

            # NSE Equity
            for inst in store.list_by_segment("EQ"):
                sym = (getattr(inst, "symbol", "") or "").upper()
                if sym:
                    new_map[sym] = {
                        "token":    getattr(inst, "isin", sym),   # isin used as token id placeholder
                        "exchange": getattr(inst, "exchange", "NSE"),
                        "segment":  "EQ",
                        "expiry":   None,
                        "strike":   None,
                        "opt_type": None,
                    }

            # NSE F&O — futures + CE + PE
            for seg in ("FUT", "CE", "PE"):
                for inst in store.list_by_segment(seg):
                    sym = (getattr(inst, "symbol", "") or "").upper()
                    if sym:
                        new_map[sym] = {
                            "token":      getattr(inst, "isin", sym),
                            "exchange":   "NFO",
                            "segment":    seg,
                            "expiry":     getattr(inst, "expiry", None),
                            "underlying": (getattr(inst, "underlying", "") or "").upper(),
                            "strike":     getattr(inst, "strike", None),
                            "opt_type":   getattr(inst, "option_type", None),
                        }

            self._map    = new_map
            self._loaded = True
            log.info(f"[token_map] Loaded {len(new_map)} tokens (EQ + NFO).")
            return len(new_map)

        except Exception as exc:
            log.warning(f"[token_map] refresh() failed: {exc} — using empty map.")
            return 0

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.refresh()

    # ── Lookups ───────────────────────────────────────────────────────────

    def get_token(self, symbol: str) -> Optional[str]:
        """Return token string for symbol, or None if not found."""
        self._ensure_loaded()
        entry = self._map.get(symbol.upper())
        return entry["token"] if entry else None

    def get_exchange(self, symbol: str) -> str:
        """Return exchange ('NSE' | 'NFO') for symbol."""
        self._ensure_loaded()
        entry = self._map.get(symbol.upper())
        return entry["exchange"] if entry else "NSE"

    # ── F&O expiry helpers ────────────────────────────────────────────────

    def get_all_expiries(self, underlying: str) -> list[str]:
        """Return all distinct expiry dates for an underlying, sorted ascending."""
        self._ensure_loaded()
        ul = underlying.upper()
        expiries = {
            v["expiry"]
            for v in self._map.values()
            if v.get("underlying") == ul and v.get("expiry")
        }
        return sorted(expiries)

    def get_near_expiry(self, underlying: str) -> Optional[str]:
        """Return the nearest future expiry date for an underlying.

        Falls back to computing next Thursday if DB has no F&O data yet.
        """
        expiries = self.get_all_expiries(underlying)
        today    = date.today().isoformat()
        future   = [e for e in expiries if e >= today]
        if future:
            return future[0]
        # Fallback: next Thursday (NIFTY weekly expiry)
        return _next_thursday().isoformat()

    def get_contracts(
        self,
        underlying: str,
        expiry: str | None = None,
        option_type: str | None = None,
    ) -> list[dict]:
        """Return all F&O contracts for an underlying, optionally filtered."""
        self._ensure_loaded()
        ul = underlying.upper()
        results = [
            {"symbol": sym, **meta}
            for sym, meta in self._map.items()
            if meta.get("underlying") == ul
            and (expiry is None     or meta.get("expiry")   == expiry)
            and (option_type is None or meta.get("opt_type") == option_type.upper())
        ]
        return sorted(results, key=lambda r: (r.get("expiry") or "", r.get("strike") or 0))

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._map)

    def __repr__(self) -> str:
        return f"<TokenMap loaded={self._loaded} symbols={len(self._map)}>"


# ── Module-level singleton + convenience functions ────────────────────────

_token_map = TokenMap()


def get_token(symbol: str) -> Optional[str]:
    """Return token for symbol from module-level singleton."""
    return _token_map.get_token(symbol)


def get_exchange(symbol: str) -> str:
    return _token_map.get_exchange(symbol)


def get_near_expiry(symbol: str) -> Optional[str]:
    return _token_map.get_near_expiry(symbol)


def get_all_expiries(symbol: str) -> list[str]:
    return _token_map.get_all_expiries(symbol)


def refresh_from_db(db_path: Path | None = None) -> int:
    """Reload the module-level token map from DB."""
    return _token_map.refresh(db_path)


# ── Helper ────────────────────────────────────────────────────────────────

def _next_thursday() -> date:
    today      = date.today()
    days_ahead = (3 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)
