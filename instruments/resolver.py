"""Instrument resolver — Phase 1.

Resolves symbol strings → canonical Instrument objects.
Handles:
  - EQ symbols:  RELIANCE → RELIANCE-EQ
  - YF symbols:  RELIANCE.NS → RELIANCE-EQ
  - FUT symbols: RELIANCE-FUT → nearest future
  - Expiry:      nearest/next monthly expiry
  - Option chain: all strikes for a given underlying + expiry

Usage:
    from instruments.resolver import InstrumentResolver
    r = InstrumentResolver()
    inst     = r.resolve("RELIANCE")         # → RELIANCE-EQ
    fut      = r.resolve("RELIANCE-FUT")     # → FUT instrument
    expiry   = r.resolve_expiry("RELIANCE")  # → nearest date
    chain    = r.resolve_chain("RELIANCE")   # → list[Instrument] CE+PE
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from core.logger import get_logger
from .models import Instrument
from .storage import InstrumentStore

log = get_logger("instruments.resolver")

# Built-in index seeds — always available even with empty SQLite store
_BUILTIN_INSTRUMENTS: list[Instrument] = [
    Instrument(
        symbol="NIFTY50-IDX", name="NIFTY 50", exchange="NSE", segment="IDX",
        underlying="NIFTY50", yf_symbol="^NSEI",
    ),
    Instrument(
        symbol="NIFTY-IDX", name="NIFTY 50", exchange="NSE", segment="IDX",
        underlying="NIFTY", yf_symbol="^NSEI",
    ),
    Instrument(
        symbol="BANKNIFTY-IDX", name="NIFTY Bank", exchange="NSE", segment="IDX",
        underlying="BANKNIFTY", yf_symbol="^NSEBANK",
    ),
    Instrument(
        symbol="SENSEX-IDX", name="BSE Sensex", exchange="BSE", segment="IDX",
        underlying="SENSEX", yf_symbol="^BSESN",
    ),
]


class InstrumentResolver:
    """Resolves raw symbol strings to canonical Instrument objects."""

    def __init__(self) -> None:
        self._store = InstrumentStore()
        self._seed_builtins()

    def _seed_builtins(self) -> None:
        """Seed built-in indices if the store is empty."""
        try:
            if self._store.count() == 0:
                self._store.insert_bulk(_BUILTIN_INSTRUMENTS)
                log.debug(f"Seeded {len(_BUILTIN_INSTRUMENTS)} built-in instruments")
        except Exception as exc:
            # Store may not support count() — fall back to in-memory builtins
            log.debug(f"Builtin seed skipped: {exc}")

    # ── Main resolver ─────────────────────────────────────────────────────

    def resolve(self, raw: str) -> Optional[Instrument]:
        """
        Resolve any symbol string to a canonical Instrument.
        Handles: RELIANCE / RELIANCE.NS / RELIANCE-EQ / RELIANCE-FUT
        """
        if not raw:
            return None

        sym = raw.strip().upper()

        # 1. Direct lookup in store
        inst = self._store.get_by_symbol(sym)
        if inst:
            return inst

        # 2. Check built-in fallback list (covers NIFTY, BANKNIFTY etc.)
        for bi in _BUILTIN_INSTRUMENTS:
            if bi.symbol == sym or bi.underlying == sym:
                return bi

        # 3. YF suffix strip: RELIANCE.NS → RELIANCE
        if sym.endswith(".NS") or sym.endswith(".BO"):
            base = sym.rsplit(".", 1)[0]
            inst = self._store.get_by_symbol(f"{base}-EQ")
            if inst:
                return inst

        # 4. Bare symbol → try EQ first, then IDX, then FUT
        for seg in ("EQ", "IDX", "FUT"):
            inst = self._store.get_by_symbol(f"{sym}-{seg}")
            if inst:
                return inst

        # 5. Fallback: search and return best match
        results = self._store.search(sym, limit=1)
        if results:
            log.debug(f"resolve('{raw}') → fallback search → {results[0].symbol}")
            return results[0]

        log.warning(f"resolve('{raw}') → not found")
        return None

    def count(self) -> int:
        """Return total number of instruments in the store."""
        try:
            return self._store.count()
        except AttributeError:
            return len(self.list_all())

    def search(self, query: str) -> list[Instrument]:
        """Full-text search across all instruments."""
        return self._store.search(query)

    def register(self, instrument: Instrument) -> None:
        """Register a custom instrument into the store."""
        self._store.insert_bulk([instrument])

    def list_all(self, exchange: str | None = None) -> list[Instrument]:
        """List all instruments, optionally filtered by exchange."""
        instruments = self._store.list_all()
        if exchange:
            return [i for i in instruments if i.exchange.upper() == exchange.upper()]
        return instruments

    def resolve_yf_symbol(self, instrument: Instrument) -> str:
        """
        Return the Yahoo Finance ticker string for an instrument.
        Equity: RELIANCE.NS
        Index:  ^NSEI
        Futures/Options: yf_symbol field if available
        """
        if instrument.yf_symbol:
            return instrument.yf_symbol
        if instrument.is_equity:
            base = (instrument.underlying or instrument.symbol.replace("-EQ", ""))
            return f"{base}.NS"
        if instrument.is_index:
            _idx_map = {
                "NIFTY50": "^NSEI",
                "NIFTY": "^NSEI",
                "BANKNIFTY": "^NSEBANK",
                "SENSEX": "^BSESN",
            }
            key = instrument.underlying or instrument.symbol.replace("-IDX", "")
            return _idx_map.get(key.upper(), f"{key}.NS")
        return instrument.yf_symbol or ""

    # ── Expiry resolver ───────────────────────────────────────────────────

    def resolve_expiry(
        self,
        underlying: str,
        which: str = "nearest",
    ) -> Optional[date]:
        """
        Return nearest or next monthly expiry for an underlying.
        which: 'nearest' | 'next' | 'far'
        """
        futures = self._store.list_by_segment("FUT")
        expiries = sorted(
            {
                f.expiry
                for f in futures
                if f.underlying == underlying.upper() and f.expiry and f.expiry >= date.today()
            }
        )
        if not expiries:
            return self._last_thursday_of_month(date.today())

        if which == "nearest":
            return expiries[0]
        elif which == "next" and len(expiries) > 1:
            return expiries[1]
        elif which == "far" and len(expiries) > 2:
            return expiries[2]
        return expiries[0]

    # ── Option chain resolver ─────────────────────────────────────────────

    def resolve_chain(
        self,
        underlying: str,
        expiry: Optional[date] = None,
        limit_strikes: int = 20,
    ) -> List[Instrument]:
        """
        Return all CE + PE instruments for underlying + expiry.
        If expiry is None, uses nearest expiry.
        """
        if expiry is None:
            expiry = self.resolve_expiry(underlying)

        chain = []
        for seg in ("CE", "PE"):
            opts = self._store.list_by_segment(seg)
            filtered = [
                o for o in opts
                if o.underlying == underlying.upper()
                and (expiry is None or o.expiry == expiry)
            ]
            filtered.sort(key=lambda x: x.strike or 0)
            chain.extend(filtered[:limit_strikes])
        return chain

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _last_thursday_of_month(d: date) -> date:
        """Compute the last Thursday of the given date's month."""
        import calendar
        year, month = d.year, d.month
        last_day = calendar.monthrange(year, month)[1]
        last = date(year, month, last_day)
        offset = (last.weekday() - 3) % 7  # 3 = Thursday
        return last - timedelta(days=offset)
