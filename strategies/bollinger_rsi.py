"""Bollinger Band + RSI Mean-Reversion Strategy — Eagle-Base.

Logic
-----
Entry  BUY  : price closes BELOW lower Bollinger Band  AND  RSI < oversold
Entry  SELL : price closes ABOVE upper Bollinger Band  AND  RSI > overbought
Exit   HOLD : price is within the bands or RSI is neutral

Why confluence?
  Bollinger Bands alone produce too many false signals in trending markets.
  Requiring RSI confirmation reduces noise and improves win-rate.

Parameters
----------
period      : BB / RSI lookback window          (default 20)
std_dev     : Band width in standard deviations (default 2.0)
oversold    : RSI threshold for long entry      (default 30)
overbought  : RSI threshold for short entry     (default 70)

Signal encoding  (BaseStrategy contract)
----------------------------------------
  1  = BUY  (go long)
 -1  = SELL (go short / exit long)
  0  = HOLD
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy, register_strategy


@register_strategy
class BollingerRsi(BaseStrategy):
    """Bollinger Band + RSI confluence mean-reversion strategy."""

    name        = "Bollinger RSI"
    version     = "1.0.0"
    description = "BB lower/upper touch + RSI oversold/overbought confluence entry"
    author      = "eagle"
    tags        = ["mean-reversion", "oscillator", "daily", "nseindia"]
    status      = "active"
    parameters  = {
        "period":     20,
        "std_dev":    2.0,
        "oversold":   30,
        "overbought": 70,
    }

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _bollinger(close: pd.Series, period: int, std_dev: float) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Return (middle, upper, lower) Bollinger Bands."""
        middle = close.rolling(period).mean()
        sigma  = close.rolling(period).std(ddof=0)
        upper  = middle + std_dev * sigma
        lower  = middle - std_dev * sigma
        return middle, upper, lower

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        """Wilder-smoothed RSI (EWM with alpha=1/period)."""
        delta  = close.diff()
        gain   = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
        loss   = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
        rs     = gain / loss.replace(0, float("nan"))
        rsi    = 100 - (100 / (1 + rs))
        return rsi.fillna(50)  # neutral default during warm-up

    # ── validate_params ──────────────────────────────────────────────────────

    def validate_params(self, params: dict) -> bool:  # type: ignore[override]
        """Extra domain checks on top of BaseStrategy.validate_params."""
        if not super().validate_params(params):
            return False
        period     = params.get("period",     self.parameters["period"])
        std_dev    = params.get("std_dev",    self.parameters["std_dev"])
        oversold   = params.get("oversold",   self.parameters["oversold"])
        overbought = params.get("overbought", self.parameters["overbought"])
        if period < 5:
            return False
        if std_dev <= 0:
            return False
        if not (0 < oversold < 50):
            return False
        if not (50 < overbought < 100):
            return False
        return True

    # ── core signal engine ───────────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Vectorised signal generation over the full OHLCV DataFrame.

        Args:
            df: Must contain at least a ``Close`` column.

        Returns:
            pd.Series[int] with values in {-1, 0, 1}, same index as ``df``.
        """
        period     = int(self.parameters.get("period",     20))
        std_dev    = float(self.parameters.get("std_dev",    2.0))
        oversold   = float(self.parameters.get("oversold",   30))
        overbought = float(self.parameters.get("overbought", 70))

        close = df["Close"].astype(float)

        _, upper, lower = self._bollinger(close, period, std_dev)
        rsi             = self._rsi(close, period)

        buy_signal  = (close < lower) & (rsi < oversold)
        sell_signal = (close > upper) & (rsi > overbought)

        signals = pd.Series(0, index=df.index, dtype=int)
        signals[buy_signal]  =  1
        signals[sell_signal] = -1

        # NaN warm-up rows → HOLD
        warmup_mask = upper.isna() | lower.isna()
        signals[warmup_mask] = 0

        return signals

    # ── on_bar (paper / live) ─────────────────────────────────────────────────

    def on_bar(self, df: pd.DataFrame) -> int:
        """Return signal for the most recent bar only.

        Called by the paper-trading executor on every new candle.
        """
        if len(df) < self.parameters["period"] + 1:
            return 0
        sig = self.generate_signals(df)
        return int(sig.iloc[-1])

    # ── metadata for position sizer ──────────────────────────────────────────

    def metadata(self) -> dict:
        """Conservative edge estimates — replace with real backtest stats."""
        return {
            "win_rate":     0.54,
            "avg_win_pct":  0.025,
            "avg_loss_pct": 0.015,
        }
