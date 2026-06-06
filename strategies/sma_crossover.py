"""SMA Crossover strategy — Phase 7 updated."""

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
