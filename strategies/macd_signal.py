"""MACD Signal Line Crossover Strategy — Phase 7 updated.

MACD momentum strategy. Uses the crossover of MACD and signal line.
Histogram-based confirmation avoids false crossovers in sideways markets.

Logic:
    BUY  — MACD line crosses ABOVE signal line (bullish momentum)
    SELL — MACD line crosses BELOW signal line (bearish momentum)
    HOLD — no crossover; or histogram too small (noise filter)

Default params: fast=12, slow=26, signal=9  (industry standard)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, register_strategy
from core.logger import logger


@register_strategy
class MacdSignal(BaseStrategy):
    """MACD line vs signal line crossover momentum strategy."""

    name        = "MACD Signal"
    version     = "1.1.0"
    description = "MACD crossover with histogram noise filter and live on_bar support."
    author      = "eagle"
    tags        = ["momentum", "daily", "swing"]
    parameters  = {"fast": 12, "slow": 26, "signal": 9, "min_histogram": 0.0}
    status      = "active"

    def __init__(
        self,
        fast: int          = 12,
        slow: int          = 26,
        signal: int        = 9,
        min_histogram: float = 0.0,
        stop_pct: float    = 0.015,
        target_pct: float  = 0.03,
    ) -> None:
        self.fast          = fast
        self.slow          = slow
        self.signal        = signal
        self.min_histogram = min_histogram
        self.stop_pct      = stop_pct
        self.target_pct    = target_pct

    def _compute_macd(self, close: pd.Series):
        ema_fast    = close.ewm(span=self.fast,   adjust=False).mean()
        ema_slow    = close.ewm(span=self.slow,   adjust=False).mean()
        macd_line   = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal, adjust=False).mean()
        histogram   = macd_line - signal_line
        return macd_line, signal_line, histogram

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        macd_line, signal_line, histogram = self._compute_macd(df["Close"])
        raw     = np.where(macd_line > signal_line, 1, -1)
        shifted = np.roll(raw, 1)
        shifted[0] = raw[0]
        crossover = raw != shifted
        strong    = np.abs(histogram) >= self.min_histogram
        signals   = np.where(crossover & strong, raw, 0)
        return pd.Series(signals, index=df.index)

    def on_bar(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.slow + self.signal + 2:
            return "HOLD"
        macd_line, signal_line, histogram = self._compute_macd(df["Close"])
        macd_now,  sig_now  = macd_line.iloc[-1],  signal_line.iloc[-1]
        macd_prev, sig_prev = macd_line.iloc[-2],  signal_line.iloc[-2]
        hist_now            = histogram.iloc[-1]
        if pd.isna(macd_now) or pd.isna(sig_now):
            return "HOLD"
        if abs(hist_now) < self.min_histogram:
            return "HOLD"
        if macd_prev <= sig_prev and macd_now > sig_now:
            return "BUY"
        if macd_prev >= sig_prev and macd_now < sig_now:
            return "SELL"
        return "HOLD"

    def validate_params(self, params: dict) -> bool:
        fast   = params.get("fast",   self.fast)
        slow   = params.get("slow",   self.slow)
        signal = params.get("signal", self.signal)
        return (
            isinstance(fast, int) and isinstance(slow, int)
            and isinstance(signal, int)
            and 0 < fast < slow and signal > 0
        )

    def stop_loss(self, entry_price: float) -> float:
        return round(entry_price * (1 - self.stop_pct), 2)

    def target(self, entry_price: float) -> float:
        return round(entry_price * (1 + self.target_pct), 2)
