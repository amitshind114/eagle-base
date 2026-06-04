"""EMA Crossover Strategy.

Exponential Moving Average crossover — faster to react than SMA due to
exponential weighting. Generates signals on both bulk DataFrames (backtesting)
and bar-by-bar (live / paper trading).

Logic:
    BUY  — fast EMA crosses ABOVE slow EMA (momentum turning bullish)
    SELL — fast EMA crosses BELOW slow EMA (momentum turning bearish)
    HOLD — no crossover on current bar

Default params: fast=12, slow=26  (mirrors MACD base)

Usage:
    strategy = EmaCrossover(fast=9, slow=21)
    runner   = BacktestRunner(symbol="RELIANCE.NS", strategy=strategy)
    result   = runner.run()
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal
from core.logger import logger


class EmaCrossover(BaseStrategy):
    """EMA crossover — faster signal vs SMA due to exponential weighting."""

    name        = "ema_crossover"
    version     = "1.1.0"
    description = "Fast/slow EMA crossover with bar-by-bar live signal support."

    def __init__(
        self,
        fast: int   = 12,
        slow: int   = 26,
        stop_pct: float = 0.015,   # 1.5% trailing stop
        target_pct: float = 0.03,  # 3% profit target
    ) -> None:
        self.fast       = fast
        self.slow       = slow
        self.stop_pct   = stop_pct
        self.target_pct = target_pct

    # ── Bulk signal generation (backtesting) ────────────────────────────────
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return Series of 1 (long) / -1 (short) / 0 (flat) for full OHLCV df."""
        fast_ema = df["Close"].ewm(span=self.fast, adjust=False).mean()
        slow_ema = df["Close"].ewm(span=self.slow, adjust=False).mean()

        raw      = np.where(fast_ema > slow_ema, 1, -1)
        # Only signal on actual crossover bars, hold otherwise
        shifted  = np.roll(raw, 1)
        shifted[0] = raw[0]
        signals  = np.where(raw != shifted, raw, 0)
        return pd.Series(signals, index=df.index)

    # ── Bar-by-bar signal (live / paper trading) ─────────────────────────────
    def on_bar(self, df: pd.DataFrame) -> Signal:
        """Return BUY / SELL / HOLD for the latest bar.

        Requires at least slow+2 bars to compute a valid crossover.
        """
        min_bars = self.slow + 2
        if len(df) < min_bars:
            return "HOLD"

        close    = df["Close"]
        fast_ema = close.ewm(span=self.fast, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow, adjust=False).mean()

        fast_now,  slow_now  = fast_ema.iloc[-1], slow_ema.iloc[-1]
        fast_prev, slow_prev = fast_ema.iloc[-2], slow_ema.iloc[-2]

        if pd.isna(fast_now) or pd.isna(slow_now):
            return "HOLD"

        # Bullish crossover: fast crossed above slow
        if fast_prev <= slow_prev and fast_now > slow_now:
            logger.debug(
                f"[ema_crossover] BUY  — fast {fast_prev:.2f}→{fast_now:.2f} "
                f"crossed above slow {slow_prev:.2f}→{slow_now:.2f}"
            )
            return "BUY"

        # Bearish crossover: fast crossed below slow
        if fast_prev >= slow_prev and fast_now < slow_now:
            logger.debug(
                f"[ema_crossover] SELL — fast {fast_prev:.2f}→{fast_now:.2f} "
                f"crossed below slow {slow_prev:.2f}→{slow_now:.2f}"
            )
            return "SELL"

        return "HOLD"

    # ── Risk parameters exposed to the risk engine ───────────────────────────
    def stop_loss(self, entry_price: float) -> float:
        """Return stop-loss price below entry."""
        return round(entry_price * (1 - self.stop_pct), 2)

    def target(self, entry_price: float) -> float:
        """Return profit-target price above entry."""
        return round(entry_price * (1 + self.target_pct), 2)
