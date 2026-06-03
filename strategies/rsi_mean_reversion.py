"""RSI Mean Reversion strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy


class RsiMeanReversion(BaseStrategy):
    """Buy oversold, sell overbought using RSI."""

    name = "RSI Mean Reversion"
    version = "1.0.0"
    description = "Mean reversion strategy using RSI overbought/oversold levels."

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0) -> None:
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(self.period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        signals = pd.Series(0, index=df.index)
        signals[rsi < self.oversold] = 1
        signals[rsi > self.overbought] = -1
        return signals
