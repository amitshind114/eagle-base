"""SMA Crossover strategy — Phase 05 updated."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy, register_strategy


@register_strategy
class SmaCrossover(BaseStrategy):
    """Go long when fast SMA crosses above slow SMA, short when below."""

    name        = "SMA Crossover"
    version     = "1.0.0"
    description = "Simple moving average crossover trend-following strategy."
    author      = "eagle"
    tags        = ["trend", "daily", "swing"]
    parameters  = {"fast": 20, "slow": 50}
    status      = "active"

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        super().__init__()   # Phase 05: copies class-level tags/parameters to instance
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_ma = df["Close"].rolling(self.fast).mean()
        slow_ma = df["Close"].rolling(self.slow).mean()
        signals = pd.Series(np.where(fast_ma > slow_ma, 1, -1), index=df.index)
        return signals

    def validate_params(self, params: dict) -> bool:
        fast = params.get("fast", self.fast)
        slow = params.get("slow", self.slow)
        return isinstance(fast, int) and isinstance(slow, int) and 0 < fast < slow

    def metadata(self) -> dict:
        """Historical edge stats — used by risk.sizer for position sizing."""
        return {
            "win_rate":     0.52,
            "avg_win_pct":  0.03,
            "avg_loss_pct": 0.02,
        }

    def on_bar(self, df: pd.DataFrame) -> int:
        """Bar-by-bar signal: 1=BUY, -1=SELL, 0=HOLD."""
        if len(df) < self.slow + 1:
            return 0
        fast_ma = df["Close"].rolling(self.fast).mean()
        slow_ma = df["Close"].rolling(self.slow).mean()
        if fast_ma.iloc[-1] > slow_ma.iloc[-1] and fast_ma.iloc[-2] <= slow_ma.iloc[-2]:
            return 1
        if fast_ma.iloc[-1] < slow_ma.iloc[-1] and fast_ma.iloc[-2] >= slow_ma.iloc[-2]:
            return -1
        return 0
