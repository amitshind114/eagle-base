"""MACD Signal Line Crossover Strategy.

MACD (Moving Average Convergence Divergence) momentum strategy.
Uses the crossover of the MACD line and the signal line to generate
BUY / SELL signals. Histogram-based confirmation avoids false crossovers
in sideways markets.

Logic:
    BUY  — MACD line crosses ABOVE signal line (bullish momentum)
    SELL — MACD line crosses BELOW signal line (bearish momentum)
    HOLD — no crossover; or histogram too small (noise filter)

Default params: fast=12, slow=26, signal=9  (industry standard)

Usage:
    strategy = MacdSignal(fast=12, slow=26, signal=9)
    runner   = BacktestRunner(symbol="INFY.NS", strategy=strategy)
    result   = runner.run()
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal
from core.logger import logger


class MacdSignal(BaseStrategy):
    """MACD line vs signal line crossover momentum strategy."""

    name        = "macd_signal"
    version     = "1.1.0"
    description = "MACD crossover with histogram noise filter and live on_bar support."

    def __init__(
        self,
        fast: int         = 12,
        slow: int         = 26,
        signal: int       = 9,
        min_histogram: float = 0.0,  # minimum absolute histogram value to avoid noise
        stop_pct: float   = 0.015,
        target_pct: float = 0.03,
    ) -> None:
        self.fast          = fast
        self.slow          = slow
        self.signal        = signal
        self.min_histogram = min_histogram
        self.stop_pct      = stop_pct
        self.target_pct    = target_pct

    # ── Internal MACD computation ────────────────────────────────────────────
    def _compute_macd(
        self, close: pd.Series
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Return (macd_line, signal_line, histogram)."""
        ema_fast    = close.ewm(span=self.fast,   adjust=False).mean()
        ema_slow    = close.ewm(span=self.slow,   adjust=False).mean()
        macd_line   = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal, adjust=False).mean()
        histogram   = macd_line - signal_line
        return macd_line, signal_line, histogram

    # ── Bulk signal generation (backtesting) ────────────────────────────────
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return Series of 1 (long) / -1 (short) / 0 (flat) for full OHLCV df."""
        macd_line, signal_line, histogram = self._compute_macd(df["Close"])

        raw     = np.where(macd_line > signal_line, 1, -1)
        shifted = np.roll(raw, 1)
        shifted[0] = raw[0]

        # Only fire on actual crossover bars + histogram filter
        crossover = raw != shifted
        strong    = np.abs(histogram) >= self.min_histogram
        signals   = np.where(crossover & strong, raw, 0)
        return pd.Series(signals, index=df.index)

    # ── Bar-by-bar signal (live / paper trading) ─────────────────────────────
    def on_bar(self, df: pd.DataFrame) -> Signal:
        """Return BUY / SELL / HOLD for the latest bar.

        Needs at least slow + signal + 2 bars for a stable calculation.
        """
        min_bars = self.slow + self.signal + 2
        if len(df) < min_bars:
            return "HOLD"

        macd_line, signal_line, histogram = self._compute_macd(df["Close"])

        macd_now,   sig_now   = macd_line.iloc[-1],  signal_line.iloc[-1]
        macd_prev,  sig_prev  = macd_line.iloc[-2],  signal_line.iloc[-2]
        hist_now              = histogram.iloc[-1]

        if pd.isna(macd_now) or pd.isna(sig_now):
            return "HOLD"

        # Noise filter: histogram must exceed minimum threshold
        if abs(hist_now) < self.min_histogram:
            return "HOLD"

        # Bullish crossover
        if macd_prev <= sig_prev and macd_now > sig_now:
            logger.debug(
                f"[macd] BUY  — MACD {macd_prev:.4f}→{macd_now:.4f} "
                f"crossed above signal {sig_prev:.4f}→{sig_now:.4f} "
                f"hist={hist_now:.4f}"
            )
            return "BUY"

        # Bearish crossover
        if macd_prev >= sig_prev and macd_now < sig_now:
            logger.debug(
                f"[macd] SELL — MACD {macd_prev:.4f}→{macd_now:.4f} "
                f"crossed below signal {sig_prev:.4f}→{sig_now:.4f} "
                f"hist={hist_now:.4f}"
            )
            return "SELL"

        return "HOLD"

    # ── Risk parameters ──────────────────────────────────────────────────────
    def stop_loss(self, entry_price: float) -> float:
        return round(entry_price * (1 - self.stop_pct), 2)

    def target(self, entry_price: float) -> float:
        return round(entry_price * (1 + self.target_pct), 2)
