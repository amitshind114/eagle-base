"""RSI Mean Reversion strategy — Phase 05 updated.

Merged from rsi_mean_reversion.py and rsi_strategy.py.
rsi_strategy.py is a thin backward-compat shim — do NOT delete.

Logic:
    BUY  — RSI crosses UP through oversold threshold
    SELL — RSI crosses UP through overbought threshold
    HOLD — no threshold crossing

Default params: period=14, oversold=30, overbought=70
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy, register_strategy


@register_strategy
class RsiMeanReversion(BaseStrategy):
    """Buy oversold, sell overbought using RSI."""

    name        = "RSI Mean Reversion"
    version     = "1.1.0"
    description = "Mean reversion strategy using RSI overbought/oversold levels."
    author      = "eagle"
    tags        = ["mean_reversion", "daily", "swing"]
    parameters  = {"period": 14, "oversold": 30.0, "overbought": 70.0}
    status      = "active"

    def __init__(
        self,
        period: int       = 14,
        oversold: float   = 30.0,
        overbought: float = 70.0,
    ) -> None:
        super().__init__()   # Phase 05: copies class-level tags/parameters to instance
        self.period     = period
        self.oversold   = oversold
        self.overbought = overbought

    # ── RSI computation (Wilder's smoothing) ─────────────────────────────────
    def _rsi(self, close: pd.Series) -> pd.Series:
        delta    = close.diff()
        gain     = delta.clip(lower=0).ewm(com=self.period - 1, min_periods=self.period).mean()
        loss     = (-delta.clip(upper=0)).ewm(com=self.period - 1, min_periods=self.period).mean()
        rs       = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    # ── Bulk signals (backtesting) ────────────────────────────────────────────
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi     = self._rsi(df["Close"])
        signals = pd.Series(0, index=df.index)
        signals[rsi < self.oversold]   = 1
        signals[rsi > self.overbought] = -1
        return signals

    # ── Bar-by-bar signal (live / paper) ─────────────────────────────────────
    def on_bar(self, df: pd.DataFrame) -> int:
        """Returns int 1/0/-1."""
        if len(df) < self.period + 2:
            return 0
        rsi      = self._rsi(df["Close"])
        rsi_now  = rsi.iloc[-1]
        rsi_prev = rsi.iloc[-2]
        if pd.isna(rsi_now) or pd.isna(rsi_prev):
            return 0
        if rsi_prev <= self.oversold  and rsi_now > self.oversold:
            return 1
        if rsi_prev <= self.overbought and rsi_now > self.overbought:
            return -1
        return 0

    def validate_params(self, params: dict) -> bool:
        period     = params.get("period",     self.period)
        oversold   = params.get("oversold",   self.oversold)
        overbought = params.get("overbought", self.overbought)
        return (
            isinstance(period, int) and period > 0
            and 0 < oversold < overbought < 100
        )

    def metadata(self) -> dict:
        """Historical edge stats — used by risk.sizer for position sizing."""
        return {
            "win_rate":     0.48,
            "avg_win_pct":  0.025,
            "avg_loss_pct": 0.018,
        }
