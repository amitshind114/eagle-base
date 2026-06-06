"""Opening Range Breakout (ORB) strategy — Phase 05 rewrite.

Opening Range Breakout logic:
  1. Identify the opening range = first N minutes of the session.
     Default: 15 minutes (3 x 5m bars, or 1 x 15m bar).
  2. Range High = highest High in the opening range.
     Range Low  = lowest  Low  in the opening range.
  3. Signal = 1  when Close breaks ABOVE Range High (bullish breakout).
     Signal = -1 when Close breaks BELOW Range Low  (bearish breakout).
     Signal = 0  during the opening range period itself.

Supported intervals: 5m, 15m (intraday only).
Required data: at least 2 full sessions of data.

Usage:
    from strategies.plugins.orb import ORBStrategy
    s = ORBStrategy(interval="5m", range_minutes=15)
    signals = s.generate_signals(df)   # df.index must be tz-aware DatetimeIndex
"""

from __future__ import annotations

import pandas as pd

from strategies.base import BaseStrategy, register_strategy


@register_strategy
class ORBStrategy(BaseStrategy):
    """Opening Range Breakout for intraday (5m / 15m) data."""

    name        = "ORB"
    version     = "1.0.0"
    description = "Opening range breakout — first-N-minute high/low define the range."
    author      = "eagle"
    tags        = ["breakout", "intraday", "5m", "15m"]
    parameters  = {"interval": "5m", "range_minutes": 15}
    status      = "active"

    # NSE session open: 09:15 IST
    _SESSION_OPEN_HOUR   = 9
    _SESSION_OPEN_MINUTE = 15

    def __init__(
        self,
        interval: str      = "5m",
        range_minutes: int = 15,
    ) -> None:
        super().__init__()  # Phase 05: copies class-level tags/parameters to instance
        self.interval      = interval
        self.range_minutes = range_minutes

    # ── helpers ──────────────────────────────────────────────────────────────

    def _bar_minutes(self) -> int:
        """Return the interval in minutes (5 for '5m', 15 for '15m')."""
        mapping = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30}
        return mapping.get(self.interval, 5)

    def _is_in_opening_range(self, ts: pd.Timestamp) -> bool:
        """Return True if timestamp falls within the opening range window."""
        session_open = ts.replace(
            hour=self._SESSION_OPEN_HOUR,
            minute=self._SESSION_OPEN_MINUTE,
            second=0, microsecond=0,
        )
        return ts < session_open + pd.Timedelta(minutes=self.range_minutes)

    def _is_session_open(self, ts: pd.Timestamp) -> bool:
        """Return True if timestamp is at or after session open."""
        session_open = ts.replace(
            hour=self._SESSION_OPEN_HOUR,
            minute=self._SESSION_OPEN_MINUTE,
            second=0, microsecond=0,
        )
        return ts >= session_open

    # ── core logic ───────────────────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Compute ORB signals over the entire DataFrame.

        Algorithm:
          For each bar:
            - If in opening range window → signal = 0 (no trade during range formation)
            - Else → look back to find the session's range High and Low
              → compare current Close to those levels → 1 / -1 / 0

        Args:
            df: OHLCV DataFrame with tz-aware DatetimeIndex (Asia/Kolkata).
                Required columns: Open, High, Low, Close.

        Returns:
            pd.Series of int with values in {-1, 0, 1}, same index as df.
        """
        if df.empty:
            return pd.Series(0, index=df.index)

        # Ensure index is DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            return pd.Series(0, index=df.index)

        signals = pd.Series(0, index=df.index, dtype=int)

        # Add a date column for grouping by trading session
        dates = df.index.normalize()  # date-only component

        for date in dates.unique():
            session_mask = dates == date
            session_df   = df[session_mask]

            if session_df.empty:
                continue

            # Find bars inside the opening range
            or_mask   = session_df.index.map(self._is_in_opening_range)
            or_bars   = session_df[or_mask]

            if or_bars.empty:
                continue

            range_high = float(or_bars["High"].max())
            range_low  = float(or_bars["Low"].min())

            # Bars AFTER the opening range — generate signals
            post_mask = ~or_mask & session_df.index.map(self._is_session_open)
            post_bars = session_df[post_mask]

            for ts, row in post_bars.iterrows():
                close = float(row["Close"])
                if close > range_high:
                    signals.at[ts] = 1
                elif close < range_low:
                    signals.at[ts] = -1
                # else: 0 (inside range — no signal)

        return signals

    def on_bar(self, df: pd.DataFrame) -> int:
        """Bar-by-bar ORB signal for live/paper trading.

        Checks if the latest bar has broken above/below today's opening range.
        Returns 1 / -1 / 0.
        """
        if len(df) < 2:
            return 0
        if not isinstance(df.index, pd.DatetimeIndex):
            return 0

        latest_ts   = df.index[-1]
        today       = latest_ts.normalize()
        today_df    = df[df.index.normalize() == today]

        or_bars = today_df[today_df.index.map(self._is_in_opening_range)]
        if or_bars.empty:
            return 0

        range_high = float(or_bars["High"].max())
        range_low  = float(or_bars["Low"].min())
        close      = float(df["Close"].iloc[-1])

        if close > range_high:
            return 1
        if close < range_low:
            return -1
        return 0

    def validate_params(self, params: dict) -> bool:
        interval      = params.get("interval",      self.interval)
        range_minutes = params.get("range_minutes", self.range_minutes)
        return (
            interval in ("1m", "3m", "5m", "15m", "30m")
            and isinstance(range_minutes, int)
            and range_minutes > 0
        )

    def metadata(self) -> dict:
        return {
            "win_rate":     0.50,
            "avg_win_pct":  0.025,
            "avg_loss_pct": 0.015,
        }
