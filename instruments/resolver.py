"""Instrument Resolver — Priority 2.

Resolves human-readable symbols to Instrument objects.
Built-in registry of 15 NSE/BSE symbols. Load full master for 20,000+.

Usage:
    resolver = InstrumentResolver()
    instrument = resolver.resolve("RELIANCE", "NSE")
    print(instrument.token, instrument.lot_size)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.logger import logger


@dataclass
class Instrument:
    """Represents a single tradeable instrument."""

    symbol: str
    token: str
    exchange: str           # NSE, BSE, NFO, MCX, CDS
    instrument_type: str    # EQ, FUT, CE, PE, IDX
    name: str = ""
    lot_size: int = 1
    tick_size: float = 0.05
    expiry: str = ""        # For F&O: 'YYYY-MM-DD'
    strike: float = 0.0     # For options
    segment: str = ""       # EQUITY, DERIVATIVE

    def __str__(self) -> str:
        return f"{self.exchange}:{self.symbol} [{self.instrument_type}]"

    @property
    def is_equity(self) -> bool:
        return self.instrument_type == "EQ"

    @property
    def is_derivative(self) -> bool:
        return self.instrument_type in ("FUT", "CE", "PE")


class InstrumentResolver:
    """Resolves symbols to Instrument objects using a local registry."""

    _BUILTIN: dict[str, dict] = {
        "NIFTY":      {"token": "26000", "exchange": "NSE", "type": "IDX", "name": "Nifty 50",                "lot_size": 75},
        "BANKNIFTY":  {"token": "26009", "exchange": "NSE", "type": "IDX", "name": "Bank Nifty",             "lot_size": 30},
        "SENSEX":     {"token": "1",     "exchange": "BSE", "type": "IDX", "name": "BSE Sensex",             "lot_size": 20},
        "RELIANCE":   {"token": "2885",  "exchange": "NSE", "type": "EQ",  "name": "Reliance Industries",   "lot_size": 1},
        "TCS":        {"token": "11536", "exchange": "NSE", "type": "EQ",  "name": "Tata Consultancy Svcs", "lot_size": 1},
        "INFY":       {"token": "1594",  "exchange": "NSE", "type": "EQ",  "name": "Infosys",               "lot_size": 1},
        "HDFCBANK":   {"token": "1333",  "exchange": "NSE", "type": "EQ",  "name": "HDFC Bank",             "lot_size": 1},
        "ICICIBANK":  {"token": "4963",  "exchange": "NSE", "type": "EQ",  "name": "ICICI Bank",            "lot_size": 1},
        "SBIN":       {"token": "3045",  "exchange": "NSE", "type": "EQ",  "name": "State Bank of India",   "lot_size": 1},
        "WIPRO":      {"token": "3787",  "exchange": "NSE", "type": "EQ",  "name": "Wipro",                 "lot_size": 1},
        "AXISBANK":   {"token": "5900",  "exchange": "NSE", "type": "EQ",  "name": "Axis Bank",             "lot_size": 1},
        "TATAMOTORS": {"token": "3456",  "exchange": "NSE", "type": "EQ",  "name": "Tata Motors",           "lot_size": 1},
        "TATASTEEL":  {"token": "3499",  "exchange": "NSE", "type": "EQ",  "name": "Tata Steel",            "lot_size": 1},
        "BAJFINANCE": {"token": "317",   "exchange": "NSE", "type": "EQ",  "name": "Bajaj Finance",         "lot_size": 1},
        "MARUTI":     {"token": "10999", "exchange": "NSE", "type": "EQ",  "name": "Maruti Suzuki",         "lot_size": 1},
    }

    def __init__(self):
        self._registry: dict[str, Instrument] = {}
        self._load_builtin()

    def _load_builtin(self) -> None:
        for symbol, meta in self._BUILTIN.items():
            self._registry[symbol.upper()] = Instrument(
                symbol=symbol,
                token=meta["token"],
                exchange=meta["exchange"],
                instrument_type=meta["type"],
                name=meta["name"],
                lot_size=meta.get("lot_size", 1),
            )
        logger.info(f"[instruments] Loaded {len(self._registry)} built-in instruments")

    def resolve(self, symbol: str, exchange: str = "NSE") -> Optional[Instrument]:
        """Resolve symbol string to an Instrument object.

        Returns Instrument if found, None otherwise.
        """
        key = symbol.upper().strip()
        instrument = self._registry.get(key)
        if instrument:
            logger.debug(f"[instruments] Resolved: {symbol} → {instrument}")
            return instrument
        logger.warning(f"[instruments] Not found: {symbol} — load full master for more symbols")
        return None

    def search(self, query: str, limit: int = 10) -> list[Instrument]:
        """Search instruments by partial symbol or name."""
        q = query.upper().strip()
        results = [
            inst for key, inst in self._registry.items()
            if q in key or q in inst.name.upper()
        ]
        return results[:limit]

    def register(self, instrument: Instrument) -> None:
        """Manually add an instrument to the registry."""
        self._registry[instrument.symbol.upper()] = instrument
        logger.debug(f"[instruments] Registered: {instrument}")

    def list_all(self, exchange: str = "") -> list[Instrument]:
        """List all instruments, optionally filtered by exchange."""
        if exchange:
            return [i for i in self._registry.values() if i.exchange == exchange.upper()]
        return list(self._registry.values())

    def count(self) -> int:
        return len(self._registry)
