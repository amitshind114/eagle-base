"""Instrument resolver — Phase 1 (Push 0 patched).

Resolves symbol strings → canonical Instrument objects.

Fixes applied
-------------
- H3 (yfinance suffix): to_yf_symbol() always ensures .NS / .BO suffix.
  Without this, yfinance silently returns empty DataFrames on raw NSE symbols.
- to_angel_symbol(): strips .NS/.BO suffix for Angel One calls.
- resolve_yf_symbol() now calls to_yf_symbol() consistently.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from core.logger import get_logger
from .models import Instrument
from .storage import InstrumentStore

log = get_logger("instruments.resolver")

_BUILTIN_INSTRUMENTS: list[Instrument] = [
    Instrument(
        symbol="NIFTY", name="NIFTY 50", exchange="NSE", segment="IDX",
        lot_size=75, tick_size=0.05, token="26000",
        nse_symbol="NIFTY", underlying="NIFTY", yf_symbol="^NSEI",
    ),
    Instrument(
        symbol="NIFTY50", name="NIFTY 50", exchange="NSE", segment="IDX",
        lot_size=75, tick_size=0.05, token="26000",
        nse_symbol="NIFTY50", underlying="NIFTY50", yf_symbol="^NSEI",
    ),
    Instrument(
        symbol="BANKNIFTY", name="NIFTY Bank", exchange="NSE", segment="IDX",
        lot_size=15, tick_size=0.05, token="26009",
        nse_symbol="BANKNIFTY", underlying="BANKNIFTY", yf_symbol="^NSEBANK",
    ),
    Instrument(
        symbol="MIDCPNIFTY", name="NIFTY Midcap Select", exchange="NSE", segment="IDX",
        lot_size=75, tick_size=0.05, token="26074",
        nse_symbol="MIDCPNIFTY", underlying="MIDCPNIFTY", yf_symbol="^NSEMDCP50",
    ),
    Instrument(
        symbol="FINNIFTY", name="NIFTY Financial Services", exchange="NSE", segment="IDX",
        lot_size=40, tick_size=0.05, token="26037",
        nse_symbol="FINNIFTY", underlying="FINNIFTY", yf_symbol="^NSEFIN15",
    ),
    Instrument(
        symbol="SENSEX", name="BSE Sensex", exchange="BSE", segment="IDX",
        lot_size=10, tick_size=0.01, token="1",
        nse_symbol="SENSEX", underlying="SENSEX", yf_symbol="^BSESN",
    ),
    Instrument(
        symbol="RELIANCE", name="Reliance Industries", exchange="NSE", segment="EQ",
        lot_size=1, tick_size=0.05, token="2885",
        nse_symbol="RELIANCE", underlying="RELIANCE", yf_symbol="RELIANCE.NS",
    ),
    Instrument(
        symbol="TATASTEEL", name="Tata Steel", exchange="NSE", segment="EQ",
        lot_size=1, tick_size=0.05, token="3499",
        nse_symbol="TATASTEEL", underlying="TATASTEEL", yf_symbol="TATASTEEL.NS",
    ),
    Instrument(
        symbol="TCS", name="Tata Consultancy Services", exchange="NSE", segment="EQ",
        lot_size=1, tick_size=0.05, token="11536",
        nse_symbol="TCS", underlying="TCS", yf_symbol="TCS.NS",
    ),
    Instrument(
        symbol="HDFCBANK", name="HDFC Bank", exchange="NSE", segment="EQ",
        lot_size=1, tick_size=0.05, token="1333",
        nse_symbol="HDFCBANK", underlying="HDFCBANK", yf_symbol="HDFCBANK.NS",
    ),
]


# ── YF / Angel symbol helpers (H3 fix) ────────────────────────────────────────

def to_yf_symbol(nse_symbol: str, exchange: str = "NSE") -> str:
    """Ensure correct Yahoo Finance suffix.

    yfinance requires RELIANCE.NS for NSE and RELIANCE.BO for BSE.
    Without the suffix, yf.download() silently returns an empty DataFrame.
    Index symbols (^NSEI etc.) are returned unchanged.
    """
    sym = nse_symbol.strip().upper()
    # Index tickers start with '^' — leave untouched
    if sym.startswith("^"):
        return sym
    # Already has correct suffix
    if sym.endswith(".NS") or sym.endswith(".BO"):
        return sym
    suffix = ".NS" if exchange.upper() in ("NSE", "NFO", "") else ".BO"
    return f"{sym}{suffix}"


def to_angel_symbol(yf_symbol: str) -> str:
    """Strip .NS / .BO suffix for Angel One API calls."""
    sym = yf_symbol.strip().upper()
    for sfx in (".NS", ".BO"):
        if sym.endswith(sfx):
            return sym[: -len(sfx)]
    return sym


class InstrumentResolver:
    """Resolves raw symbol strings to canonical Instrument objects."""

    def __init__(self) -> None:
        self._store = InstrumentStore()
        self._seed_builtins()

    def _seed_builtins(self) -> None:
        try:
            if self.count() == 0:
                self._store.insert_bulk(_BUILTIN_INSTRUMENTS)
                log.debug(f"Seeded {len(_BUILTIN_INSTRUMENTS)} built-in instruments")
        except Exception as exc:
            log.debug(f"Builtin seed skipped: {exc}")

    def resolve(self, raw: str) -> Optional[Instrument]:
        """Resolve any symbol string to a canonical Instrument."""
        if not raw:
            return None

        sym = raw.strip().upper()

        inst = self._store.get_by_symbol(sym)
        if inst:
            return inst

        if sym.endswith(".NS") or sym.endswith(".BO"):
            base = sym.rsplit(".", 1)[0]
            inst = self._store.get_by_symbol(base)
            if inst:
                return inst
            inst = self._store.get_by_symbol(f"{base}-EQ")
            if inst:
                return inst

        for suffix in ("-EQ", "-IDX", "-FUT", "-CE", "-PE"):
            if sym.endswith(suffix):
                base = sym[: -len(suffix)]
                inst = self._store.get_by_symbol(base)
                if inst:
                    return inst

        for bi in _BUILTIN_INSTRUMENTS:
            if bi.symbol == sym or bi.underlying == sym or bi.nse_symbol == sym:
                return bi

        results = self.search(sym)
        if results:
            log.debug(f"resolve('{raw}') → fallback search → {results[0].symbol}")
            return results[0]

        log.warning(f"resolve('{raw}') → not found")
        return None

    def count(self) -> int:
        raw = self._store.count()
        return sum(raw.values())

    def search(self, query: str) -> list[Instrument]:
        results = self._store.search(query)
        if results:
            return results
        q = query.strip().upper()
        return [
            inst for inst in _BUILTIN_INSTRUMENTS
            if q in inst.symbol.upper() or q in (inst.name or "").upper()
        ]

    def register(self, instrument: Instrument) -> None:
        self._store.insert_bulk([instrument])

    def list_all(self, exchange: str | None = None) -> list[Instrument]:
        from instruments.storage import _ALL_TABLES
        results: list[Instrument] = []
        for table in _ALL_TABLES:
            rows = self._store.list_all(table)
            insts = [self._store._from_dict(r) for r in rows]
            results.extend(insts)
        if exchange:
            ex_upper = exchange.upper()
            results = [
                i for i in results
                if getattr(i, "exchange", "").upper() == ex_upper
            ]
        return results

    def resolve_yf_symbol(self, instrument: Instrument) -> str:
        """Return the Yahoo Finance ticker, guaranteeing correct suffix."""
        # Stored yf_symbol takes priority if already correct
        if instrument.yf_symbol:
            return to_yf_symbol(instrument.yf_symbol, instrument.exchange)
        if instrument.is_index:
            _idx_map = {
                "NIFTY50":    "^NSEI",
                "NIFTY":      "^NSEI",
                "BANKNIFTY":  "^NSEBANK",
                "SENSEX":     "^BSESN",
                "MIDCPNIFTY": "^NSEMDCP50",
                "FINNIFTY":   "^NSEFIN15",
            }
            key = instrument.underlying or instrument.symbol.replace("-IDX", "")
            mapped = _idx_map.get(key.upper())
            if mapped:
                return mapped
        base = instrument.nse_symbol or instrument.underlying or instrument.symbol
        return to_yf_symbol(base, instrument.exchange)

    # ── Expiry resolver ───────────────────────────────────────────────────

    def resolve_expiry(
        self,
        underlying: str,
        which: str = "nearest",
    ) -> Optional[date]:
        futures = self._store.list_by_segment("FUT")
        expiries = sorted(
            {
                f.expiry
                for f in futures
                if f.underlying == underlying.upper()
                and f.expiry
                and f.expiry >= date.today()
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

    @staticmethod
    def _last_thursday_of_month(d: date) -> date:
        import calendar
        year, month = d.year, d.month
        last_day = calendar.monthrange(year, month)[1]
        last     = date(year, month, last_day)
        offset   = (last.weekday() - 3) % 7
        return last - timedelta(days=offset)
