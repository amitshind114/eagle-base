"""Abstract base for all strategies.

Every strategy must implement `generate_signals(df)`.
Optionally implement `metadata()` to unlock automatic position sizing
via risk.sizer — without it the sizer falls back to 1% risk per trade.

Optional `atr(df)` delegates to ai.indicators so strategies don\'t need
to recompute it inline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    name:        str = "BaseStrategy"
    version:     str = "1.0.0"
    description: str = ""

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return Series of 1 (long), -1 (short), 0 (flat), aligned to df."""
        ...

    def metadata(self) -> dict:
        """Return historical edge stats used by risk.sizer for position sizing.

        Strategies that override this get automatic, volatility-adjusted
        position sizing.  Those that don\'t fall back to 1% risk per trade.

        Keys:
            win_rate      float  0–1    e.g. 0.58
            avg_win_pct   float  0–1    average winning trade as fraction of capital
            avg_loss_pct  float  0–1    average losing trade as fraction of capital
        """
        return {}

    def atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """ATR as a fraction of close price, delegated to ai.indicators.

        Returns a Series aligned to df.  Falls back to a simple TR-based
        calculation if ai.indicators is unavailable.
        """
        try:
            from ai.indicators import atr as _atr
            return _atr(df, period=period) / df["Close"]
        except Exception:
            high  = df["High"]
            low   = df["Low"]
            close = df["Close"]
            prev  = close.shift(1)
            tr    = pd.concat([
                high - low,
                (high - prev).abs(),
                (low  - prev).abs(),
            ], axis=1).max(axis=1)
            atr_series = tr.ewm(span=period, adjust=False).mean()
            return (atr_series / close.replace(0, float("nan"))).fillna(0)

    def sized_qty(
        self,
        price: float,
        df: pd.DataFrame,
        capital: float,
        lot_size: int = 1,
    ) -> int:
        """Return a position-sized quantity using risk.sizer.

        Uses metadata() for Kelly inputs and atr(df) for volatility scalar.
        Falls back to a conservative 1% risk per trade if metadata is empty.
        """
        from risk.sizer import PositionSizer
        meta       = self.metadata()
        win_rate   = float(meta.get("win_rate",     0.50))
        avg_win    = float(meta.get("avg_win_pct",  0.02))
        avg_loss   = float(meta.get("avg_loss_pct", 0.01))
        atr_pct    = float(self.atr(df).iloc[-1]) if not df.empty else 0.015
        sizer      = PositionSizer(total_capital=capital)
        result     = sizer.size(
            symbol=self.name, price=price,
            win_rate=win_rate, avg_win_pct=avg_win, avg_loss_pct=avg_loss,
            atr_pct=atr_pct,  lot_size=lot_size,
        )
        return result.qty

    def __repr__(self) -> str:
        return f"{self.name} v{self.version}"
