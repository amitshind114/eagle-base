"""Eagle-Base Candle Domain Model.

OHLCV candle with validation, derived metrics,
and utility methods used by strategies and backtesting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Candle(BaseModel):
    """A single OHLCV candle bar.

    Validates:
    - high >= low
    - high >= open, close
    - low <= open, close
    - volume >= 0
    """

    model_config = {"frozen": True}

    timestamp: datetime
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    volume: float = Field(default=0.0, ge=0)
    oi: Optional[float] = Field(default=None, ge=0, description="Open interest")
    interval: str = Field(default="1d", description="e.g. 1m, 5m, 15m, 1h, 1d")
    symbol: str = Field(default="")

    @model_validator(mode="after")
    def validate_ohlc(self) -> "Candle":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) cannot be less than low ({self.low})")
        if self.high < self.open:
            raise ValueError(f"high ({self.high}) cannot be less than open ({self.open})")
        if self.high < self.close:
            raise ValueError(f"high ({self.high}) cannot be less than close ({self.close})")
        if self.low > self.open:
            raise ValueError(f"low ({self.low}) cannot be greater than open ({self.open})")
        if self.low > self.close:
            raise ValueError(f"low ({self.low}) cannot be greater than close ({self.close})")
        return self

    # --- Derived metrics (computed properties, not stored) ---

    @property
    def body(self) -> float:
        """Absolute candle body size."""
        return abs(self.close - self.open)

    @property
    def upper_shadow(self) -> float:
        """Upper wick size."""
        return self.high - max(self.open, self.close)

    @property
    def lower_shadow(self) -> float:
        """Lower wick size."""
        return min(self.open, self.close) - self.low

    @property
    def range(self) -> float:
        """High - Low range."""
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        """Body is less than 10% of range."""
        if self.range == 0:
            return True
        return (self.body / self.range) < 0.1

    @property
    def change_pct(self) -> float:
        """Percentage change from open to close."""
        if self.open == 0:
            return 0.0
        return ((self.close - self.open) / self.open) * 100

    @property
    def typical_price(self) -> float:
        """(High + Low + Close) / 3 — used in VWAP, pivot points."""
        return (self.high + self.low + self.close) / 3

    def __str__(self) -> str:
        direction = "▲" if self.is_bullish else "▼"
        return (
            f"{self.symbol} {self.timestamp.strftime('%Y-%m-%d %H:%M')} "
            f"O={self.open:.2f} H={self.high:.2f} L={self.low:.2f} "
            f"C={self.close:.2f} {direction} V={self.volume:.0f}"
        )
