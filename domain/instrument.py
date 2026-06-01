"""Eagle-Base Instrument Domain Model.

Represents any tradeable or reference instrument:
Equity, Futures, Options (CE/PE), Index, ETF, Bond.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from domain.enums import Exchange, InstrumentType, OptionType
from core.logger import logger


class Instrument(BaseModel):
    """Full instrument definition with validation.

    Supports EQ, FUT, CE, PE, INDEX, ETF, BOND.
    Option-specific fields (strike, option_type, expiry) are
    validated to be present when instrument_type is CE or PE.
    """

    model_config = {"frozen": False, "validate_assignment": True}

    # --- Identity ---
    symbol: str = Field(..., min_length=1, description="Human-readable symbol e.g. NIFTY, RELIANCE")
    trading_symbol: str = Field(..., min_length=1, description="Broker trading symbol e.g. NIFTY24JUNFUT")
    token: str = Field(..., min_length=1, description="Broker instrument token")
    exchange: Exchange
    instrument_type: InstrumentType

    # --- Equity / General ---
    name: str = Field(default="", description="Full company/index name")
    isin: Optional[str] = Field(default=None, description="ISIN code for equities")

    # --- F&O Specific ---
    expiry: Optional[date] = Field(default=None, description="Expiry date for FUT/CE/PE")
    strike: Optional[float] = Field(default=None, ge=0, description="Strike price for options")
    option_type: OptionType = Field(default=OptionType.NA)

    # --- Contract Specs ---
    lot_size: int = Field(default=1, ge=1, description="Lot size for F&O contracts")
    tick_size: float = Field(default=0.05, gt=0, description="Minimum price movement")
    multiplier: float = Field(default=1.0, gt=0, description="Contract value multiplier")

    # --- Market Data Snapshot (optional, populated live) ---
    last_price: Optional[float] = Field(default=None, ge=0)
    upper_circuit: Optional[float] = Field(default=None)
    lower_circuit: Optional[float] = Field(default=None)

    @field_validator("symbol", "trading_symbol")
    @classmethod
    def uppercase_symbols(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Instrument token cannot be empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_option_fields(self) -> "Instrument":
        """Options must have strike, expiry, and correct option_type."""
        is_option = self.instrument_type in (InstrumentType.CE, InstrumentType.PE)
        if is_option:
            if self.strike is None:
                raise ValueError(f"{self.instrument_type} instrument must have a strike price")
            if self.expiry is None:
                raise ValueError(f"{self.instrument_type} instrument must have an expiry date")
            expected_type = OptionType(self.instrument_type.value)
            if self.option_type != expected_type:
                logger.warning(
                    f"option_type mismatch: instrument_type={self.instrument_type}, "
                    f"option_type={self.option_type}. Auto-correcting."
                )
                self.option_type = expected_type
        return self

    @model_validator(mode="after")
    def validate_futures_expiry(self) -> "Instrument":
        """Futures must have an expiry."""
        if self.instrument_type == InstrumentType.FUT and self.expiry is None:
            raise ValueError("FUT instrument must have an expiry date")
        return self

    @property
    def is_derivative(self) -> bool:
        return self.instrument_type in (InstrumentType.FUT, InstrumentType.CE, InstrumentType.PE)

    @property
    def is_option(self) -> bool:
        return self.instrument_type in (InstrumentType.CE, InstrumentType.PE)

    @property
    def is_equity(self) -> bool:
        return self.instrument_type == InstrumentType.EQ

    @property
    def is_index(self) -> bool:
        return self.instrument_type == InstrumentType.INDEX

    def contract_value(self, price: float) -> float:
        """Calculate notional contract value at given price."""
        return price * self.lot_size * self.multiplier

    def __str__(self) -> str:
        parts = [f"{self.exchange.value}:{self.symbol}({self.instrument_type.value})"]
        if self.is_option and self.strike and self.expiry:
            parts.append(f"Strike={self.strike} Expiry={self.expiry}")
        return " ".join(parts)

    def __repr__(self) -> str:
        return (
            f"Instrument(symbol={self.symbol!r}, type={self.instrument_type.value}, "
            f"exchange={self.exchange.value}, token={self.token!r})"
        )
