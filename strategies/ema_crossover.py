"""EMA Crossover Strategy — Phase 7 updated.

Exponential Moving Average crossover — faster to react than SMA.
Generates signals on both bulk DataFrames (backtesting) and bar-by-bar
(live / paper trading).

Logic:
    BUY  — fast EMA crosses ABOVE slow EMA (momentum turning bullish)
    SELL — fast EMA crosses BELOW slow EMA (momentum turning bearish)
    HOLD — no crossover on current bar

Default params: fast=12, slow=26  (mirrors MACD base)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, register_strategy
from core.logger import logger


@register_strategy
class EmaCrossover(BaseStrategy):
    """EMA crossover — faster signal vs SMA due to exponential weighting."""

    name        = "EMA Crossover"
    version     = "1.1.0"
    description = "Fast/slow EMA crossover with bar-by-bar live signal support."
    author      = "eagle"
    tags        = ["trend", "daily", "swing", "intraday"]
    parameters  = {"fast": 12, "slow": 26, "stop_pct": 0.015, "target_pct": 0.03}
    status      = "active"

    def __init__(
        self,
        fast: int        = 12,
        slow: int        = 26,
        stop_pct: float  = 0.015,
        target_pct: float = 0.03,
    ) -> None:
        self.fast       = fast
        self.slow       = slow
        self.stop_pct   = stop_pct
        self.target_pct = target_pct

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_ema = df["Close"].ewm(span=self.fast, adjust=False).mean()
        slow_ema = df["Close"].ewm(span=self.slow, adjust=False).mean()
        raw      = np.where(fast_ema > slow_ema, 1, -1)
        shifted  = np.roll(raw, 1)
        shifted[0] = raw[0]
        signals  = np.where(raw != shifted, raw, 0)
        return pd.Series(signals, index=df.index)

    def on_bar(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.slow + 2:
            return "HOLD"
        close    = df["Close"]
        fast_ema = close.ewm(span=self.fast, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow, adjust=False).mean()
        fast_now, slow_now   = fast_ema.iloc[-1], slow_ema.iloc[-1]
        fast_prev, slow_prev = fast_ema.iloc[-2], slow_ema.iloc[-2]
        if pd.isna(fast_now) or pd.isna(slow_now):
            return "HOLD"
        if fast_prev <= slow_prev and fast_now > slow_now:
            return "BUY"
        if fast_prev >= slow_prev and fast_now < slow_now:
            return "SELL"
        return "HOLD"

    def validate_params(self, params: dict) -> bool:
        fast = params.get("fast", self.fast)
        slow = params.get("slow", self.slow)
        return isinstance(fast, int) and isinstance(slow, int) and 0 < fast < slow

    def stop_loss(self, entry_price: float) -> float:
        return round(entry_price * (1 - self.stop_pct), 2)

    def target(self, entry_price: float) -> float:
        return round(entry_price * (1 + self.target_pct), 2)
