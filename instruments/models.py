"""Instrument domain models."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class Instrument(BaseModel):
    """Single tradable instrument — equity, future, option or index.

    Fields
    ------
    symbol        : canonical key  e.g. RELIANCE-EQ or RELIANCE
    name          : full company / index name
    exchange      : NSE | BSE | NFO | MCX
    segment       : EQ | FUT | CE | PE | IDX
    token         : Angel One numeric token (str) — required for every broker call
    isin          : ISIN code
    lot_size      : contract lot size (1 for equities)
    tick_size     : minimum price movement
    sector        : sector classification
    industry      : industry classification
    underlying    : parent symbol for derivatives
    expiry        : expiry date for F&O contracts
    strike        : strike price for options
    option_type   : CE | PE | None
    yf_symbol     : Yahoo Finance ticker  e.g. RELIANCE.NS
    nse_symbol    : raw NSE symbol without suffix  e.g. RELIANCE
    angel_token   : alias for token — kept for explicit Angel One call sites
    """

    # Core identity
    symbol: str
    name: str = ""
    exchange: str = "NSE"               # NSE | BSE | NFO | MCX
    segment: str = "EQ"                 # EQ | FUT | CE | PE | IDX

    # Broker token — required for Angel One orders, WebSocket, and historical data
    token: str = ""                     # numeric string e.g. "2885"
    angel_token: str = ""               # alias — always kept in sync with token

    # NSE canonical symbol (no .NS suffix)
    nse_symbol: str = ""                # e.g. "RELIANCE"

    # Instrument details
    isin: str = ""
    lot_size: int = 1
    tick_size: float = 0.05
    sector: str = ""
    industry: str = ""

    # F&O specific
    underlying: Optional[str] = None
    expiry: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None   # CE | PE

    # Yahoo Finance
    yf_symbol: str = ""                 # e.g. "RELIANCE.NS"

    def model_post_init(self, __context) -> None:
        """Keep token and angel_token in sync; derive nse_symbol if missing."""
        # Sync token ↔ angel_token
        if self.token and not self.angel_token:
            object.__setattr__(self, "angel_token", self.token)
        elif self.angel_token and not self.token:
            object.__setattr__(self, "token", self.angel_token)

        # Derive nse_symbol from symbol if not set
        if not self.nse_symbol:
            base = self.symbol
            for sfx in ("-EQ", "-FUT", "-CE", "-PE", "-IDX", ".NS", ".BO"):
                if base.upper().endswith(sfx):
                    base = base[: -len(sfx)]
                    break
            object.__setattr__(self, "nse_symbol", base.upper())

    # ── Segment helpers ────────────────────────────────────────────────────

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
        return self.segment.upper() in ("FUT", "CE", "PE", "OPT", "FUTURES", "OPTIONS")

    def display(self) -> str:
        """Human-readable label for UI dropdowns."""
        if self.is_future:
            return (
                f"{self.underlying} {self.expiry.strftime('%b').upper()} FUT"
                if self.expiry
                else f"{self.symbol} FUT"
            )
        if self.is_option:
            return (
                f"{self.underlying} {int(self.strike or 0)} {self.option_type}"
                if self.expiry
                else self.symbol
            )
        return f"{self.symbol} — {self.name}" if self.name else self.symbol
