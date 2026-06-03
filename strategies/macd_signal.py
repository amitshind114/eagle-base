"""MACD Signal Line Crossover strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy


class MacdSignal(BaseStrategy):
    """Long when MACD crosses above signal line, short when below."""

    name = "MACD Signal"
    version = "1.0.0"
    description = "MACD line vs signal line crossover momentum strategy."

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        ema_fast = df["Close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df["Close"].ewm(span=self.slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal, adjust=False).mean()
        signals = pd.Series(np.where(macd_line > signal_line, 1, -1), index=df.index)
        return signals
