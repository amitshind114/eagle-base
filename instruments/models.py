"""Instrument domain models — Phase 1."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class Instrument(BaseModel):
    """Single tradable instrument — equity, future, option or index."""

    symbol: str                          # canonical key  e.g. RELIANCE-EQ
    name: str                            # full company name
    exchange: str = "NSE"               # NSE | BSE
    segment: str = "EQ"                  # EQ | FUT | CE | PE | IDX
    isin: str = ""
    lot_size: int = 1
    tick_size: float = 0.05
    sector: str = ""
    industry: str = ""

    # F&O specific
    underlying: Optional[str] = None     # RELIANCE for futures/options
    expiry: Optional[date] = None        # expiry date for F&O
    strike: Optional[float] = None       # strike for options
    option_type: Optional[str] = None    # CE | PE | None

    # Yahoo Finance ticker
    yf_symbol: str = ""                  # RELIANCE.NS

    @property
    def is_equity(self) -> bool:
        return self.segment == "EQ"

    @property
    def is_future(self) -> bool:
        return self.segment == "FUT"

    @property
    def is_option(self) -> bool:
        return self.segment in ("CE", "PE")

    @property
    def is_index(self) -> bool:
        return self.segment == "IDX"

    def display(self) -> str:
        """Human-readable label for UI dropdowns."""
        if self.is_future:
            return f"{self.underlying} {self.expiry.strftime('%b').upper()} FUT" if self.expiry else f"{self.symbol} FUT"
        if self.is_option:
            return f"{self.underlying} {int(self.strike or 0)} {self.option_type}" if self.expiry else self.symbol
        return f"{self.symbol} — {self.name}"
