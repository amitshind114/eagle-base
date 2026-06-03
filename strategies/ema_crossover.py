"""EMA Crossover strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy


class EmaCrossover(BaseStrategy):
    """EMA crossover — faster signal vs SMA due to exponential weighting."""

    name = "EMA Crossover"
    version = "1.0.0"
    description = "Exponential moving average crossover strategy."

    def __init__(self, fast: int = 12, slow: int = 26) -> None:
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_ema = df["Close"].ewm(span=self.fast, adjust=False).mean()
        slow_ema = df["Close"].ewm(span=self.slow, adjust=False).mean()
        signals = pd.Series(np.where(fast_ema > slow_ema, 1, -1), index=df.index)
        return signals
