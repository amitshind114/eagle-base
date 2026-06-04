"""Opening Range Breakout (ORB) Strategy — NSE Intraday.

One of the most widely used intraday strategies on NSE/BSE.
Captures the directional breakout that often occurs when price moves
beyond the high or low established in the first N minutes of the session.

Logic:
    1. Define opening range: high and low of the first `orb_minutes` candles
       after market open (09:15 IST by default).
    2. BUY  signal — close of any subsequent candle breaks above range high.
    3. SELL signal — close of any subsequent candle breaks below range low.
    4. No new trades after `cutoff_time` (default 14:00 IST) to avoid
       end-of-day reversals.
    5. Stop-loss placed at the opposite end of the opening range.

Requirements:
    - Intraday OHLCV DataFrame with a DatetimeIndex in IST.
    - Columns: Open, High, Low, Close, Volume.
    - Typical timeframe: 1-min or 5-min candles.

Usage:
    strategy = ORBStrategy(orb_minutes=15)
    runner   = BacktestRunner(symbol="NIFTY50", strategy=strategy, interval="5m")
    result   = runner.run()
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy, Signal
from core.logger import logger


class ORBStrategy(BaseStrategy):
    """Opening Range Breakout — intraday breakout after initial range forms."""

    name        = "orb"
    version     = "1.0.0"
    description = "Opening Range Breakout — breakout above/below first-N-minute range."

    # NSE market open in IST
    MARKET_OPEN = "09:15"

    def __init__(
        self,
        orb_minutes: int   = 15,      # duration of opening range in minutes
        cutoff_time: str   = "14:00", # no new entries after this time (IST)
        stop_pct: float    = 0.005,   # 0.5% stop beyond range boundary
        target_ratio: float = 2.0,    # risk:reward — target = stop * ratio
    ) -> None:
        self.orb_minutes  = orb_minutes
        self.cutoff_time  = cutoff_time
        self.stop_pct     = stop_pct
        self.target_ratio = target_ratio

        # State reset each trading day
        self._range_high: float | None = None
        self._range_low:  float | None = None
        self._range_set:  bool         = False
        self._traded_today: bool       = False
        self._last_date:  str | None   = None

    # ── Bulk signal generation (backtesting) ────────────────────────────────
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Vectorized ORB signals across a full intraday DataFrame."""
        signals = pd.Series(0, index=df.index)

        if not isinstance(df.index, pd.DatetimeIndex):
            logger.warning("[orb] DataFrame index must be DatetimeIndex for ORB.")
            return signals

        for date, day_df in df.groupby(df.index.date):
            # Opening range: first orb_minutes candles from 09:15
            open_time   = pd.Timestamp(f"{date} {self.MARKET_OPEN}", tz=day_df.index.tz)
            range_end   = open_time + pd.Timedelta(minutes=self.orb_minutes)
            cutoff      = pd.Timestamp(f"{date} {self.cutoff_time}", tz=day_df.index.tz)

            orb_mask    = (day_df.index >= open_time) & (day_df.index < range_end)
            trade_mask  = (day_df.index >= range_end) & (day_df.index < cutoff)

            if orb_mask.sum() == 0:
                continue

            orb_high = day_df.loc[orb_mask, "High"].max()
            orb_low  = day_df.loc[orb_mask, "Low"].min()

            traded = False
            for ts, row in day_df.loc[trade_mask].iterrows():
                if traded:
                    break
                if row["Close"] > orb_high:
                    signals.at[ts] = 1
                    traded = True
                elif row["Close"] < orb_low:
                    signals.at[ts] = -1
                    traded = True

        return signals

    # ── Bar-by-bar signal (live / paper trading) ─────────────────────────────
    def on_bar(self, df: pd.DataFrame) -> Signal:
        """Live bar-by-bar ORB signal.

        Manages opening range state internally; resets each new trading day.
        """
        if df.empty:
            return "HOLD"

        last_bar  = df.iloc[-1]
        ts        = df.index[-1]

        if not isinstance(ts, pd.Timestamp):
            return "HOLD"

        current_date = str(ts.date())
        current_time = ts.strftime("%H:%M")

        # Reset state on new trading day
        if current_date != self._last_date:
            self._range_high   = None
            self._range_low    = None
            self._range_set    = False
            self._traded_today = False
            self._last_date    = current_date

        # No new trades after cutoff
        if current_time >= self.cutoff_time:
            return "HOLD"

        # One trade per day rule
        if self._traded_today:
            return "HOLD"

        # Build opening range during first orb_minutes
        open_dt   = pd.Timestamp(f"{current_date} {self.MARKET_OPEN}", tz=ts.tz)
        range_end = open_dt + pd.Timedelta(minutes=self.orb_minutes)

        if ts < range_end:
            # Still inside opening range window — track high/low
            h = float(last_bar["High"])
            l = float(last_bar["Low"])
            self._range_high = max(self._range_high or h, h)
            self._range_low  = min(self._range_low  or l, l)
            return "HOLD"

        # Opening range is now locked
        if not self._range_set:
            self._range_set = True
            logger.info(
                f"[orb] Range set for {current_date}: "
                f"high={self._range_high:.2f}  low={self._range_low:.2f}"
            )

        close = float(last_bar["Close"])

        if close > (self._range_high or 0):
            logger.debug(f"[orb] BUY  — close {close:.2f} > range_high {self._range_high:.2f}")
            self._traded_today = True
            return "BUY"

        if close < (self._range_low or float("inf")):
            logger.debug(f"[orb] SELL — close {close:.2f} < range_low {self._range_low:.2f}")
            self._traded_today = True
            return "SELL"

        return "HOLD"

    # ── Risk parameters ──────────────────────────────────────────────────────
    def stop_loss(self, entry_price: float, direction: str = "BUY") -> float:
        """Stop-loss placed at the opposite range boundary ± stop_pct buffer."""
        if direction == "BUY" and self._range_low is not None:
            return round(self._range_low * (1 - self.stop_pct), 2)
        if direction == "SELL" and self._range_high is not None:
            return round(self._range_high * (1 + self.stop_pct), 2)
        return round(entry_price * (1 - self.stop_pct), 2)

    def target(self, entry_price: float, direction: str = "BUY") -> float:
        """Target = entry +/- (stop distance × target_ratio)."""
        sl   = self.stop_loss(entry_price, direction)
        dist = abs(entry_price - sl)
        if direction == "BUY":
            return round(entry_price + dist * self.target_ratio, 2)
        return round(entry_price - dist * self.target_ratio, 2)
