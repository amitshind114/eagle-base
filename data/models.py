"""Data domain models."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict


class OHLCV(BaseModel):
    """Single OHLCV bar."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
