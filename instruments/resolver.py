"""Instrument resolver — Phase 1.

Resolves symbol strings → canonical Instrument objects.
Handles:
  - EQ symbols:  RELIANCE → RELIANCE (EQ instrument, symbol=RELIANCE)
  - YF symbols:  RELIANCE.NS → RELIANCE-EQ
  - FUT symbols: RELIANCE-FUT → nearest future
  - Expiry:      nearest/next monthly expiry
  - Option chain: all strikes for a given underlying + expiry

Usage:
    from instruments.resolver import InstrumentResolver
    r = InstrumentResolver()
    inst     = r.resolve("RELIANCE")         # → RELIANCE equity instrument
    expiry   = r.resolve_expiry("RELIANCE")  # → nearest date
    chain    = r.resolve_chain("RELIANCE")   # → list[Instrument] CE+PE

FIX P10:
  - count() now returns int (sum of all segments) rather than delegating to
    InstrumentStore.count() which returns a dict. Tests use `count() > 0`.
  - list_all(exchange=...) now filters in Python after fetching all tables,
    because InstrumentStorage.list_all(table) takes a table name, not an
    exchange kwarg.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from core.logger import get_logger
from .models import Instrument
from .storage import InstrumentStore

log = get_logger("instruments.resolver")

# Built-in seeds — always available even with empty SQLite store.
# token values match NSE instrument master (used by broker APIs).
_BUILTIN_INSTRUMENTS: list[Instrument] = [
    Instrument(
        symbol="NIFTY", name="NIFTY 50", exchange="NSE", segment="IDX",
        lot_size=75, tick_size=0.05,
        token="26000",
        underlying="NIFTY", yf_symbol="^NSEI",
    ),
    Instrument(
        symbol="NIFTY50", name="NIFTY 50", exchange="NSE", segment="IDX",
        lot_size=75, tick_size=0.05,
        token="26000",
        underlying="NIFTY50", yf_symbol="^NSEI",
    ),
    Instrument(
        symbol="BANKNIFTY", name="NIFTY Bank", exchange="NSE", segment="IDX",
        lot_size=15, tick_size=0.05,
        token="26009",
        underlying="BANKNIFTY", yf_symbol="^NSEBANK",
    ),
    Instrument(
        symbol="SENSEX", name="BSE Sensex", exchange="BSE", segment="IDX",
        lot_size=10, tick_size=0.01,
        token="1",
        underlying="SENSEX", yf_symbol="^BSESN",
    ),
    Instrument(
        symbol="RELIANCE", name="Reliance Industries", exchange="NSE", segment="EQ",
        lot_size=1, tick_size=0.05,
        token="2885",
        underlying="RELIANCE", yf_symbol="RELIANCE.NS",
    ),
    Instrument(
        symbol="TATASTEEL", name="Tata Steel", exchange="NSE", segment="EQ",
        lot_size=1, tick_size=0.05,
        token="3499",
        underlying="TATASTEEL", yf_symbol="TATASTEEL.NS",
    ),
    Instrument(
        symbol="TCS", name="Tata Consultancy Services", exchange="NSE", segment="EQ",
        lot_size=1, tick_size=0.05,
        token="11536",
        underlying="TCS", yf_symbol="TCS.NS",
    ),
    Instrument(
        symbol="HDFCBANK", name="HDFC Bank", exchange="NSE", segment="EQ",
        lot_size=1, tick_size=0.05,
        token="1333",
        underlying="HDFCBANK", yf_symbol="HDFCBANK.NS",
    ),
]


class InstrumentResolver:
    """Resolves raw symbol strings to canonical Instrument objects."""

    def __init__(self) -> None:
        self._store = InstrumentStore()
        self._seed_builtins()

    def _seed_builtins(self) -> None:
        """Seed built-in instruments if the store is empty."""
        try:
            if self.count() == 0:
                self._store.insert_bulk(_BUILTIN_INSTRUMENTS)
                log.debug(f"Seeded {len(_BUILTIN_INSTRUMENTS)} built-in instruments")
        except Exception as exc:
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

        # 1. Direct lookup in store (exact symbol match)
        inst = self._store.get_by_symbol(sym)
        if inst:
            return inst

        # 2. YF suffix strip: RELIANCE.NS → RELIANCE
        if sym.endswith(".NS") or sym.endswith(".BO"):
            base = sym.rsplit(".", 1)[0]
            inst = self._store.get_by_symbol(base)
            if inst:
                return inst
            # also try -EQ suffix variant
            inst = self._store.get_by_symbol(f"{base}-EQ")
            if inst:
                return inst

        # 3. Strip segment suffix and retry bare: RELIANCE-EQ → RELIANCE
        for suffix in ("-EQ", "-IDX", "-FUT", "-CE", "-PE"):
            if sym.endswith(suffix):
                base = sym[: -len(suffix)]
                inst = self._store.get_by_symbol(base)
                if inst:
                    return inst

        # 4. Check built-in fallback list (in-memory safety net)
        for bi in _BUILTIN_INSTRUMENTS:
            if bi.symbol == sym or bi.underlying == sym:
                return bi

        # 5. Fallback: full-text search, return best match
        results = self._store.search(sym, limit=1)
        if results:
            log.debug(f"resolve('{raw}') → fallback search → {results[0].symbol}")
            return results[0]

        log.warning(f"resolve('{raw}') → not found")
        return None

    def count(self) -> int:
        """Return total number of instruments in the store as a single int.

        FIX P10: InstrumentStore.count() returns a dict {EQ: N, FUT: N, ...}.
        This method sums all values so callers can do `count() > 0`.
        """
        raw = self._store.count()  # dict[str, int]
        return sum(raw.values())

    def search(self, query: str) -> list[Instrument]:
        """Full-text search across all instruments."""
        return self._store.search(query)

    def register(self, instrument: Instrument) -> None:
        """Register a custom instrument into the store."""
        self._store.insert_bulk([instrument])

    def list_all(self, exchange: str | None = None) -> list[Instrument]:
        """List all instruments, optionally filtered by exchange.

        FIX P10: InstrumentStorage.list_all(table) takes a table name positional
        arg, not an 'exchange' kwarg. We iterate all four tables ourselves and
        filter by exchange in Python.
        """
        from instruments.storage import _ALL_TABLES, _SEG_TABLE
        results: list[Instrument] = []
        for table in _ALL_TABLES:
            rows = self._store.list_all(table)          # list[dict]
            insts = [self._store._from_dict(r) for r in rows]
            results.extend(insts)
        if exchange:
            ex_upper = exchange.upper()
            results = [i for i in results if getattr(i, "exchange", "").upper() == ex_upper]
        return results

    def resolve_yf_symbol(self, instrument: Instrument) -> str:
        """
        Return the Yahoo Finance ticker string for an instrument.
        Equity: RELIANCE.NS
        Index:  ^NSEI
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
