"""SMA Crossover strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy


class SmaCrossover(BaseStrategy):
    """Go long when fast SMA crosses above slow SMA, short when below."""

    name = "SMA Crossover"
    version = "1.0.0"
    description = "Simple moving average crossover trend-following strategy."

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_ma = df["Close"].rolling(self.fast).mean()
        slow_ma = df["Close"].rolling(self.slow).mean()
        signals = pd.Series(np.where(fast_ma > slow_ma, 1, -1), index=df.index)
        return signals
