"""Instrument registry — Phase 1.

Single entry point for all instrument lookups in the system.
Backed by SQLite via InstrumentStore.
Falls back to hardcoded NIFTY50 list if SQLite master is unavailable.

Usage:
    from instruments.registry import InstrumentRegistry
    reg = InstrumentRegistry()
    inst = reg.get("RELIANCE")          # → Instrument
    results = reg.search("HDFC")        # → list[Instrument]
    syms = reg.list_by_segment("FUT")   # → list[Instrument]
    underlyings = reg.list_underlyings() # → list[str]  e.g. ["RELIANCE","TCS",...]
"""

from __future__ import annotations

from typing import List, Optional

from core.logger import get_logger
from core.exceptions import InstrumentNotFoundError
from .models import Instrument
from .search import InstrumentSearch
from .resolver import InstrumentResolver

log = get_logger("instruments.registry")

# ── Fallback hardcoded universe (used only if SQLite master is empty) ─────
_FALLBACK: dict[str, dict] = {
    "RELIANCE":   {"name": "Reliance Industries",       "sector": "Energy",         "lot_size": 250},
    "TCS":        {"name": "Tata Consultancy Services", "sector": "IT",             "lot_size": 150},
    "HDFCBANK":   {"name": "HDFC Bank",                 "sector": "Banking",        "lot_size": 550},
    "INFY":       {"name": "Infosys",                   "sector": "IT",             "lot_size": 300},
    "ICICIBANK":  {"name": "ICICI Bank",                "sector": "Banking",        "lot_size": 700},
    "ITC":        {"name": "ITC Ltd",                   "sector": "FMCG",          "lot_size": 3200},
    "SBIN":       {"name": "State Bank of India",       "sector": "Banking",        "lot_size": 1500},
    "HINDUNILVR": {"name": "Hindustan Unilever",        "sector": "FMCG",          "lot_size": 300},
    "BHARTIARTL": {"name": "Bharti Airtel",             "sector": "Telecom",        "lot_size": 950},
    "KOTAKBANK":  {"name": "Kotak Mahindra Bank",       "sector": "Banking",        "lot_size": 400},
    "LT":         {"name": "Larsen & Toubro",           "sector": "Infrastructure", "lot_size": 175},
    "WIPRO":      {"name": "Wipro",                     "sector": "IT",             "lot_size": 1500},
    "AXISBANK":   {"name": "Axis Bank",                 "sector": "Banking",        "lot_size": 1200},
    "MARUTI":     {"name": "Maruti Suzuki",             "sector": "Auto",           "lot_size": 100},
    "TATAMOTORS": {"name": "Tata Motors",               "sector": "Auto",           "lot_size": 1425},
    "SUNPHARMA":  {"name": "Sun Pharma",                "sector": "Pharma",         "lot_size": 700},
    "TITAN":      {"name": "Titan Company",             "sector": "Consumer",       "lot_size": 375},
    "BAJFINANCE": {"name": "Bajaj Finance",             "sector": "NBFC",           "lot_size": 125},
    "NIFTY":      {"name": "Nifty 50 Index",            "sector": "Index",          "lot_size": 50,  "segment": "IDX"},
    "BANKNIFTY":  {"name": "Bank Nifty Index",          "sector": "Index",          "lot_size": 15,  "segment": "IDX"},
}


class InstrumentRegistry:
    """Primary instrument registry. Backed by SQLite, falls back to hardcoded."""

    def __init__(self) -> None:
        try:
            self._search = InstrumentSearch()
            self._resolver = InstrumentResolver()
            self._use_db = True
            log.info(f"Registry ready (DB): {self._search.stats()}")
        except Exception as exc:
            log.warning(f"SQLite init failed ({exc}), using fallback registry.")
            self._use_db = False

    # ── Public API ────────────────────────────────────────────────────────

    def get(self, symbol: str) -> Instrument:
        """Get instrument by symbol. Raises InstrumentNotFoundError if missing."""
        if self._use_db:
            inst = self._resolver.resolve(symbol)
            if inst:
                return inst
        inst = self._fallback_get(symbol)
        if inst:
            return inst
        raise InstrumentNotFoundError(f"Instrument '{symbol}' not found.")

    def search(self, query: str) -> List[Instrument]:
        """Search by symbol or name. Returns EQ first, then FUT, CE, PE."""
        if self._use_db:
            return self._search.search(query)
        return self._fallback_search(query)

    def list_by_segment(self, segment: str) -> List[Instrument]:
        """List all instruments for a segment (EQ / FUT / CE / PE / IDX)."""
        if self._use_db:
            return self._search.list_segment(segment)
        return [i for i in self._fallback_all() if i.segment == segment.upper()]

    def list_fo_underlyings(self) -> List[str]:
        """List all F&O eligible underlying symbols (e.g. RELIANCE, NIFTY)."""
        if self._use_db:
            return self._search.list_fo_underlyings()
        return list(_FALLBACK.keys())

    def list_underlyings(self) -> List[str]:
        """Alias for list_fo_underlyings().

        Returns every symbol that has futures or options listed on NSE.
        Used by MultiStockRunner, PortfolioEngine, and Walk-Forward tester.

        Example:
            reg = InstrumentRegistry()
            symbols = reg.list_underlyings()
            # → ["RELIANCE", "TCS", "HDFCBANK", ..., "NIFTY", "BANKNIFTY"]
        """
        return self.list_fo_underlyings()

    def resolve_yf(self, symbol: str) -> str:
        """Return Yahoo Finance ticker for a symbol."""
        if self._use_db:
            inst = self._resolver.resolve(symbol)
            if inst:
                return self._resolver.resolve_yf_symbol(inst)
        return f"{symbol.upper().replace('-EQ','')}.NS"

    def refresh(self, force: bool = False) -> None:
        """Refresh instrument master from NSE."""
        if self._use_db:
            self._search.refresh(force=force)

    def stats(self) -> dict:
        if self._use_db:
            return self._search.stats()
        return {"fallback": len(_FALLBACK)}

    # ── Fallback ──────────────────────────────────────────────────────────

    def _fallback_get(self, symbol: str) -> Optional[Instrument]:
        key = symbol.upper().replace("-EQ", "").replace(".NS", "")
        d = _FALLBACK.get(key)
        if not d:
            return None
        return self._make_fallback(key, d)

    def _fallback_search(self, query: str) -> List[Instrument]:
        q = query.lower()
        return [
            self._make_fallback(k, v)
            for k, v in _FALLBACK.items()
            if q in k.lower() or q in v["name"].lower() or q in v["sector"].lower()
        ]

    def _fallback_all(self) -> List[Instrument]:
        return [self._make_fallback(k, v) for k, v in _FALLBACK.items()]

    @staticmethod
    def _make_fallback(sym: str, d: dict) -> Instrument:
        seg = d.get("segment", "EQ")
        return Instrument(
            symbol=f"{sym}-{seg}",
            name=d["name"],
            exchange="NSE",
            segment=seg,
            lot_size=d.get("lot_size", 1),
            sector=d.get("sector", ""),
            underlying=sym,
            yf_symbol=f"{sym}.NS",
        )
