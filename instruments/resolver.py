"""Instrument Resolver — Priority 2.

Resolves human-readable symbols (e.g. NIFTY, RELIANCE)
to exchange tokens and instrument metadata.

TODO (Phase 4 - Priority 2):
- Load instrument master from Angel One
- Build symbol → token lookup map
- Support NSE, BSE, NFO segments
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
    exchange: str  # NSE, BSE, NFO, MCX
    instrument_type: str  # EQ, FUT, OPT, IDX
    lot_size: int = 1
    tick_size: float = 0.05
    name: str = ""


class InstrumentResolver:
    """Resolves symbols to Instrument objects."""

    def __init__(self):
        self._registry: dict[str, Instrument] = {}

    def resolve(self, symbol: str, exchange: str = "NSE") -> Optional[Instrument]:
        """Resolve symbol to Instrument. TODO: Phase 4 Priority 2."""
        logger.debug(f"Resolving: {symbol} on {exchange}")
        raise NotImplementedError("TODO: Phase 4 Priority 2 — implement symbol resolution")

    def load_master(self, source: str = "angel_one") -> int:
        """Load instrument master list. Returns count of instruments loaded."""
        logger.info(f"Loading instrument master from: {source}")
        raise NotImplementedError("TODO: Phase 4 Priority 2 — load instrument master")

    def search(self, query: str) -> list[Instrument]:
        """Search instruments by partial name or symbol."""
        raise NotImplementedError("TODO: Phase 4 Priority 2 — implement search")
