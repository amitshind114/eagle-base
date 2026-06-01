"""SMA Crossover Strategy — Priority 4.

Classic dual moving average crossover.
  BUY  when fast SMA crosses ABOVE slow SMA (golden cross)
  SELL when fast SMA crosses BELOW slow SMA (death cross)

Default: SMA(20) / SMA(50)

Usage:
    from strategies.sma_crossover import SMACrossoverStrategy
    from backtesting.runner import BacktestRunner

    strategy = SMACrossoverStrategy(fast=20, slow=50)
    runner = BacktestRunner(symbol="RELIANCE.NS", strategy=strategy)
    result = runner.run()
    print(result.summary())
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy, Signal
from core.logger import logger


class SMACrossoverStrategy(BaseStrategy):
    """SMA crossover — BUY on golden cross, SELL on death cross."""

    name = "sma_crossover"
    description = "Dual SMA crossover — golden cross buy, death cross sell"
    version = "1.0.0"

    def __init__(self, fast: int = 20, slow: int = 50):
        super().__init__(fast=fast, slow=slow)
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        self.fast = fast
        self.slow = slow

    def on_bar(self, df: pd.DataFrame) -> Signal:
        """Return BUY/SELL/HOLD based on SMA crossover."""
        if len(df) < self.slow + 1:
            return "HOLD"  # Not enough data yet

        close = df["Close"]
        fast_sma = close.rolling(self.fast).mean()
        slow_sma = close.rolling(self.slow).mean()

        # Current and previous values
        fast_now  = fast_sma.iloc[-1]
        fast_prev = fast_sma.iloc[-2]
        slow_now  = slow_sma.iloc[-1]
        slow_prev = slow_sma.iloc[-2]

        if pd.isna(fast_now) or pd.isna(slow_now) or pd.isna(fast_prev) or pd.isna(slow_prev):
            return "HOLD"

        # Golden cross: fast crosses above slow
        if fast_prev <= slow_prev and fast_now > slow_now:
            logger.debug(f"[sma] GOLDEN CROSS — fast={fast_now:.2f} slow={slow_now:.2f}")
            return "BUY"

        # Death cross: fast crosses below slow
        if fast_prev >= slow_prev and fast_now < slow_now:
            logger.debug(f"[sma] DEATH CROSS  — fast={fast_now:.2f} slow={slow_now:.2f}")
            return "SELL"

        return "HOLD"
