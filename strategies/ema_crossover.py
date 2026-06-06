"""EMA Crossover strategy — Phase 05 updated."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy, register_strategy


@register_strategy
class EmaCrossover(BaseStrategy):
    """Go long when fast EMA crosses above slow EMA, short when below."""

    name        = "EMA Crossover"
    version     = "1.1.0"
    description = "Exponential moving average crossover trend-following strategy."
    author      = "eagle"
    tags        = ["trend", "daily", "swing"]
    parameters  = {"fast": 12, "slow": 26}
    status      = "active"

    def __init__(self, fast: int = 12, slow: int = 26) -> None:
        super().__init__()   # Phase 05: copies class-level tags/parameters to instance
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_ema = df["Close"].ewm(span=self.fast, adjust=False).mean()
        slow_ema = df["Close"].ewm(span=self.slow, adjust=False).mean()
        signals  = pd.Series(np.where(fast_ema > slow_ema, 1, -1), index=df.index)
        return signals

    def validate_params(self, params: dict) -> bool:
        fast = params.get("fast", self.fast)
        slow = params.get("slow", self.slow)
        return isinstance(fast, int) and isinstance(slow, int) and 0 < fast < slow

    def metadata(self) -> dict:
        """Historical edge stats — used by risk.sizer for position sizing."""
        return {
            "win_rate":     0.54,
            "avg_win_pct":  0.035,
            "avg_loss_pct": 0.02,
        }

    def on_bar(self, df: pd.DataFrame) -> int:
        """Bar-by-bar signal: 1=BUY, -1=SELL, 0=HOLD."""
        if len(df) < self.slow + 1:
            return 0
        fast_ema = df["Close"].ewm(span=self.fast, adjust=False).mean()
        slow_ema = df["Close"].ewm(span=self.slow, adjust=False).mean()
        if fast_ema.iloc[-1] > slow_ema.iloc[-1] and fast_ema.iloc[-2] <= slow_ema.iloc[-2]:
            return 1
        if fast_ema.iloc[-1] < slow_ema.iloc[-1] and fast_ema.iloc[-2] >= slow_ema.iloc[-2]:
            return -1
        return 0
