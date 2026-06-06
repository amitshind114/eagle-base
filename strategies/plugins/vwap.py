"""VWAP Deviation Mean-Reversion strategy — Phase 05 rewrite.

VWAP Deviation logic:
  VWAP = cumulative(typical_price * volume) / cumulative(volume)
         where typical_price = (High + Low + Close) / 3

  Signal = 1  (BUY)  when price is > deviation% BELOW VWAP  → expect mean reversion up
  Signal = -1 (SELL) when price is > deviation% ABOVE VWAP  → expect mean reversion down
  Signal = 0  (HOLD) when price is within the band

Default deviation threshold: 2%

Grace handling:
  - Volume column missing → returns all-zero signals (logged as warning)
  - Volume column all-zero → returns all-zero signals
  - VWAP = 0 at any bar → skip that bar (treat as HOLD)

Usage:
    from strategies.plugins.vwap import VWAPStrategy
    s = VWAPStrategy(deviation_pct=2.0)
    signals = s.generate_signals(df)   # df must have High, Low, Close, Volume
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy, register_strategy
from core.logger import get_logger

log = get_logger("strategies.plugins.vwap")


@register_strategy
class VWAPStrategy(BaseStrategy):
    """VWAP deviation mean-reversion strategy."""

    name        = "VWAP Deviation"
    version     = "1.0.0"
    description = "Mean reversion when price deviates >N% from session VWAP."
    author      = "eagle"
    tags        = ["mean_reversion", "intraday", "vwap"]
    parameters  = {"deviation_pct": 2.0, "session_reset": True}
    status      = "active"

    def __init__(
        self,
        deviation_pct: float = 2.0,
        session_reset: bool  = True,
    ) -> None:
        super().__init__()  # Phase 05: copies class-level tags/parameters to instance
        self.deviation_pct = deviation_pct
        self.session_reset = session_reset

    # ── VWAP calculation ─────────────────────────────────────────────────────

    def _compute_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Compute rolling session VWAP.

        If session_reset=True and index is tz-aware DatetimeIndex:
          VWAP resets at the start of each trading day (09:15 session open).
        Otherwise:
          cumulative VWAP over the entire DataFrame.

        Returns:
            pd.Series of VWAP values, same index as df.
            NaN where Volume is zero or insufficient data.
        """
        typical = (df["High"] + df["Low"] + df["Close"]) / 3.0
        vol     = df["Volume"].copy()

        # Zero-volume bars contribute zero to VWAP (avoid division by zero)
        vol_safe = vol.replace(0, pd.NA)

        tpv = typical * vol  # typical-price × volume

        if self.session_reset and isinstance(df.index, pd.DatetimeIndex):
            dates   = df.index.normalize()
            cum_tpv = tpv.groupby(dates).cumsum()
            cum_vol = vol.groupby(dates).cumsum()
        else:
            cum_tpv = tpv.cumsum()
            cum_vol = vol.cumsum()

        # Replace zero cumulative volume with NaN to avoid VWAP = 0 artifacts
        vwap = cum_tpv / cum_vol.replace(0, float("nan"))
        return vwap

    # ── core logic ───────────────────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Compute VWAP deviation signals over the entire DataFrame.

        Args:
            df: OHLCV DataFrame. Required columns: High, Low, Close, Volume.

        Returns:
            pd.Series of int with values in {-1, 0, 1}, same index as df.
            All zeros if Volume column is missing or all-zero.
        """
        signals = pd.Series(0, index=df.index, dtype=int)

        # Grace: Volume column missing
        if "Volume" not in df.columns:
            log.warning("[VWAPStrategy] 'Volume' column missing — returning all-zero signals.")
            return signals

        # Grace: Volume all zero
        if df["Volume"].sum() == 0:
            log.warning("[VWAPStrategy] All Volume values are zero — VWAP undefined, returning all-zero signals.")
            return signals

        vwap = self._compute_vwap(df)
        threshold = self.deviation_pct / 100.0

        # Avoid division by zero or NaN VWAP
        valid = vwap.notna() & (vwap != 0)

        deviation = (df["Close"] - vwap) / vwap.where(valid)

        # BUY: price is > deviation% BELOW vwap (negative deviation)
        signals[valid & (deviation < -threshold)] = 1
        # SELL: price is > deviation% ABOVE vwap (positive deviation)
        signals[valid & (deviation > threshold)] = -1

        return signals

    def on_bar(self, df: pd.DataFrame) -> int:
        """Bar-by-bar VWAP signal for live/paper trading."""
        if len(df) < 2:
            return 0
        if "Volume" not in df.columns or df["Volume"].sum() == 0:
            return 0

        vwap = self._compute_vwap(df)
        last_vwap  = vwap.iloc[-1]
        last_close = df["Close"].iloc[-1]

        if pd.isna(last_vwap) or last_vwap == 0:
            return 0

        deviation = (last_close - last_vwap) / last_vwap
        threshold = self.deviation_pct / 100.0

        if deviation < -threshold:
            return 1
        if deviation > threshold:
            return -1
        return 0

    def validate_params(self, params: dict) -> bool:
        deviation_pct = params.get("deviation_pct", self.deviation_pct)
        return isinstance(deviation_pct, (int, float)) and 0 < deviation_pct < 100

    def metadata(self) -> dict:
        return {
            "win_rate":     0.51,
            "avg_win_pct":  0.02,
            "avg_loss_pct": 0.015,
        }
