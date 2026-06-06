"""MACD Signal strategy — Phase 05 updated."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy, register_strategy


@register_strategy
class MacdSignal(BaseStrategy):
    """MACD crossover strategy: long when MACD line crosses above signal line."""

    name        = "MACD Signal"
    version     = "1.1.0"
    description = "MACD line / signal line crossover momentum strategy."
    author      = "eagle"
    tags        = ["momentum", "trend", "daily"]
    parameters  = {"fast": 12, "slow": 26, "signal": 9}
    status      = "active"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        super().__init__()   # Phase 05: copies class-level tags/parameters to instance
        self.fast   = fast
        self.slow   = slow
        self.signal = signal

    def _macd(self, close: pd.Series) -> tuple[pd.Series, pd.Series]:
        ema_fast   = close.ewm(span=self.fast,   adjust=False).mean()
        ema_slow   = close.ewm(span=self.slow,   adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal, adjust=False).mean()
        return macd_line, signal_line

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        macd_line, signal_line = self._macd(df["Close"])
        signals = pd.Series(np.where(macd_line > signal_line, 1, -1), index=df.index)
        return signals

    def on_bar(self, df: pd.DataFrame) -> int:
        """Bar-by-bar signal: 1=BUY, -1=SELL, 0=HOLD."""
        if len(df) < self.slow + self.signal + 1:
            return 0
        macd_line, signal_line = self._macd(df["Close"])
        curr_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
        prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
        if pd.isna(curr_diff) or pd.isna(prev_diff):
            return 0
        if prev_diff <= 0 and curr_diff > 0:
            return 1
        if prev_diff >= 0 and curr_diff < 0:
            return -1
        return 0

    def validate_params(self, params: dict) -> bool:
        fast   = params.get("fast",   self.fast)
        slow   = params.get("slow",   self.slow)
        signal = params.get("signal", self.signal)
        return (
            isinstance(fast,   int) and fast > 0
            and isinstance(slow,   int) and slow > fast
            and isinstance(signal, int) and signal > 0
        )

    def metadata(self) -> dict:
        """Historical edge stats — used by risk.sizer for position sizing."""
        return {
            "win_rate":     0.50,
            "avg_win_pct":  0.04,
            "avg_loss_pct": 0.025,
        }
