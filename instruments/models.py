"""Instrument domain models — Phase 1."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class Instrument(BaseModel):
    """Single tradable instrument — equity, future, option or index.

    Fields:
        symbol        : canonical key  e.g. RELIANCE-EQ or RELIANCE
        name          : full company name
        exchange      : NSE | BSE
        segment       : EQ | FUT | CE | PE | IDX
        token         : exchange instrument token (e.g. NSE token '2885' for RELIANCE)
        isin          : ISIN code
        lot_size      : contract lot size (1 for equities)
        tick_size     : minimum price movement
        sector        : sector classification
        industry      : industry classification
        underlying    : parent symbol for derivatives (RELIANCE for RELIANCE FUT)
        expiry        : expiry date for F&O contracts
        strike        : strike price for options
        option_type   : CE | PE | None
        yf_symbol     : Yahoo Finance ticker (RELIANCE.NS)
    """

    symbol: str                          # canonical key  e.g. RELIANCE-EQ
    name: str                            # full company name
    exchange: str = "NSE"               # NSE | BSE
    segment: str = "EQ"                  # EQ | FUT | CE | PE | IDX
    token: str = ""                      # exchange instrument token
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
        return self.segment.upper() in ("EQ", "EQUITY")

    @property
    def is_future(self) -> bool:
        return self.segment.upper() in ("FUT", "FUTURES")

    @property
    def is_option(self) -> bool:
        return self.segment.upper() in ("CE", "PE", "OPT", "OPTIONS")

    @property
    def is_index(self) -> bool:
        return self.segment.upper() in ("IDX", "INDEX")

    @property
    def is_derivative(self) -> bool:
        """True for futures and options."""
        return self.segment.upper() in ("FUT", "CE", "PE", "OPT", "FUTURES", "OPTIONS")

    def display(self) -> str:
        """Human-readable label for UI dropdowns."""
        if self.is_future:
            return f"{self.underlying} {self.expiry.strftime('%b').upper()} FUT" if self.expiry else f"{self.symbol} FUT"
        if self.is_option:
            return f"{self.underlying} {int(self.strike or 0)} {self.option_type}" if self.expiry else self.symbol
        return f"{self.symbol} — {self.name}"
