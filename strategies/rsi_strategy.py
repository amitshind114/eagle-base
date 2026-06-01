"""RSI Strategy — Priority 4.

Relative Strength Index mean-reversion strategy.
  BUY  when RSI crosses above oversold threshold (default 30)
  SELL when RSI crosses above overbought threshold (default 70)

Default: RSI(14), oversold=30, overbought=70

Usage:
    from strategies.rsi_strategy import RSIStrategy
    from backtesting.runner import BacktestRunner

    strategy = RSIStrategy(period=14, oversold=30, overbought=70)
    runner = BacktestRunner(symbol="TCS.NS", strategy=strategy)
    result = runner.run()
    print(result.summary())
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy, Signal
from core.logger import logger


class RSIStrategy(BaseStrategy):
    """RSI mean-reversion — buy oversold, sell overbought."""

    name = "rsi_strategy"
    description = "RSI mean-reversion — buy at oversold, sell at overbought"
    version = "1.0.0"

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        super().__init__(period=period, oversold=oversold, overbought=overbought)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def _compute_rsi(self, close: pd.Series) -> pd.Series:
        """Compute RSI using Wilder's smoothing (EWM)."""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=self.period - 1, min_periods=self.period).mean()
        avg_loss = loss.ewm(com=self.period - 1, min_periods=self.period).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        return 100 - (100 / (1 + rs))

    def on_bar(self, df: pd.DataFrame) -> Signal:
        """Return BUY/SELL/HOLD based on RSI levels."""
        if len(df) < self.period + 2:
            return "HOLD"

        rsi = self._compute_rsi(df["Close"])
        rsi_now  = rsi.iloc[-1]
        rsi_prev = rsi.iloc[-2]

        if pd.isna(rsi_now) or pd.isna(rsi_prev):
            return "HOLD"

        # BUY: RSI crosses up through oversold
        if rsi_prev <= self.oversold and rsi_now > self.oversold:
            logger.debug(f"[rsi] BUY  — RSI {rsi_prev:.1f} → {rsi_now:.1f} (oversold cross)")
            return "BUY"

        # SELL: RSI crosses up through overbought
        if rsi_prev <= self.overbought and rsi_now > self.overbought:
            logger.debug(f"[rsi] SELL — RSI {rsi_prev:.1f} → {rsi_now:.1f} (overbought cross)")
            return "SELL"

        return "HOLD"
