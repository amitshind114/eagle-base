"""VWAP Mean-Reversion Strategy — NSE Intraday.

VWAP (Volume Weighted Average Price) is the benchmark intraday price used
by institutions. Retail price tends to revert to VWAP after deviating too far.
This strategy trades that reversion.

Logic:
    1. Compute rolling intraday VWAP: cumsum(price * volume) / cumsum(volume)
       where price = (High + Low + Close) / 3  (typical price)
    2. Compute deviation bands using rolling standard deviation of typical price.
    3. BUY  — price drops below  VWAP - (band_mult × std)  → expect reversion up
    4. SELL — price rises above VWAP + (band_mult × std)  → expect reversion down
    5. HOLD — price within bands, or outside market hours
    6. VWAP resets to zero at market open each day (intraday anchored).

Requirements:
    - Intraday OHLCV DataFrame with DatetimeIndex in IST.
    - Columns: Open, High, Low, Close, Volume.
    - Typical timeframe: 1-min or 5-min candles.

Usage:
    strategy = VWAPStrategy(band_mult=1.5)
    runner   = BacktestRunner(symbol="BANKNIFTY", strategy=strategy, interval="5m")
    result   = runner.run()
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy, Signal
from core.logger import logger


class VWAPStrategy(BaseStrategy):
    """VWAP mean-reversion — buy below lower band, sell above upper band."""

    name        = "vwap"
    version     = "1.0.0"
    description = "Intraday VWAP mean-reversion with standard-deviation bands."

    MARKET_OPEN = "09:15"

    def __init__(
        self,
        band_mult: float   = 1.5,    # std-dev multiplier for entry bands
        std_window: int    = 20,     # rolling window for std calculation
        cutoff_time: str   = "14:30",
        stop_pct: float    = 0.008,  # 0.8% stop
        target_pct: float  = 0.012,  # 1.2% target (1.5× risk)
    ) -> None:
        self.band_mult   = band_mult
        self.std_window  = std_window
        self.cutoff_time = cutoff_time
        self.stop_pct    = stop_pct
        self.target_pct  = target_pct

    # ── VWAP computation ─────────────────────────────────────────────────────
    @staticmethod
    def _typical_price(df: pd.DataFrame) -> pd.Series:
        return (df["High"] + df["Low"] + df["Close"]) / 3

    def _compute_vwap(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return df with added columns: vwap, vwap_upper, vwap_lower."""
        tp      = self._typical_price(df)
        cum_vol = df["Volume"].cumsum()
        vwap    = (tp * df["Volume"]).cumsum() / cum_vol.replace(0, float("nan"))

        std         = tp.rolling(self.std_window, min_periods=1).std().fillna(0)
        upper_band  = vwap + self.band_mult * std
        lower_band  = vwap - self.band_mult * std

        out               = df.copy()
        out["vwap"]       = vwap
        out["vwap_upper"] = upper_band
        out["vwap_lower"] = lower_band
        return out

    # ── Bulk signal generation (backtesting) ────────────────────────────────
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Vectorized VWAP signals. VWAP is reset per trading day."""
        signals = pd.Series(0, index=df.index)

        if not isinstance(df.index, pd.DatetimeIndex):
            logger.warning("[vwap] DataFrame index must be DatetimeIndex.")
            return signals

        for _date, day_df in df.groupby(df.index.date):
            enriched = self._compute_vwap(day_df)
            for ts, row in enriched.iterrows():
                if str(ts.strftime("%H:%M")) >= self.cutoff_time:
                    continue
                if row["Close"] < row["vwap_lower"]:
                    signals.at[ts] = 1
                elif row["Close"] > row["vwap_upper"]:
                    signals.at[ts] = -1

        return signals

    # ── Bar-by-bar signal (live / paper trading) ─────────────────────────────
    def on_bar(self, df: pd.DataFrame) -> Signal:
        """Live VWAP signal on latest bar.

        Slices today's bars from df to compute an intraday-anchored VWAP.
        """
        if df.empty:
            return "HOLD"

        ts = df.index[-1]
        if not isinstance(ts, pd.Timestamp):
            return "HOLD"

        current_time = ts.strftime("%H:%M")
        if current_time >= self.cutoff_time:
            return "HOLD"

        # Keep only today's bars for intraday-anchored VWAP
        today    = ts.date()
        today_df = df[df.index.date == today]

        if len(today_df) < 2:
            return "HOLD"

        enriched  = self._compute_vwap(today_df)
        last      = enriched.iloc[-1]
        close     = float(last["Close"])
        vwap      = float(last["vwap"])
        upper     = float(last["vwap_upper"])
        lower     = float(last["vwap_lower"])

        if pd.isna(vwap):
            return "HOLD"

        if close < lower:
            logger.debug(
                f"[vwap] BUY  — close {close:.2f} < lower_band {lower:.2f} "
                f"(VWAP {vwap:.2f})"
            )
            return "BUY"

        if close > upper:
            logger.debug(
                f"[vwap] SELL — close {close:.2f} > upper_band {upper:.2f} "
                f"(VWAP {vwap:.2f})"
            )
            return "SELL"

        return "HOLD"

    # ── Risk parameters ──────────────────────────────────────────────────────
    def stop_loss(self, entry_price: float) -> float:
        return round(entry_price * (1 - self.stop_pct), 2)

    def target(self, entry_price: float) -> float:
        return round(entry_price * (1 + self.target_pct), 2)
