"""AI signal models."""

from __future__ import annotations

from pydantic import BaseModel


class SignalResult(BaseModel):
    symbol: str
    ltp: float
    rsi: float
    macd_bullish: bool
    ema_cross: str  # 'bullish', 'bearish', 'none'
    bb_position: str  # 'above', 'below', 'inside'
    volume_spike: bool
    score: int
    signals: list[str]
    recommendation: str
