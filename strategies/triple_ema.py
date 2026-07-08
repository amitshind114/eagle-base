"""Triple EMA Strategy — Eagle-Base.

Signal logic:
  - All three conditions must hold for a BUY:
      fast EMA (9) > medium EMA (21) > slow EMA (55)
      AND fast crossed above medium this bar
  - All three conditions must hold for a SELL:
      fast EMA (9) < medium EMA (21) < slow EMA (55)
      AND fast crossed below medium this bar
  - No signal while EMAs are warming up or no crossover this bar → None

The triple-confirmation filter reduces false signals compared to a
standard two-EMA crossover by requiring the price structure to be
aligned across all three timeframes simultaneously.

Position sizing:
  - Allocates up to MAX_POSITION_PCT (default 95%) of capital per position
  - Position size = floor(capital * pct / price)
  - Will not open a new position if one is already open in same direction

Required bar format (from StrategyRunner._fetch_latest_bar)::

    {
        "symbol":    str,
        "open":      float,
        "high":      float,
        "low":       float,
        "close":     float,
        "volume":    float,
        "timestamp": str,
    }

Usage::

    strategy = TripleEMAStrategy(
        symbol="RELIANCE",
        capital=50000.0,
        params={"fast_period": 9, "medium_period": 21, "slow_period": 55},
    )
    signal = strategy.on_bar(bar)  # {"side": "BUY", "qty": 10} or None

Backtest usage (BaseStrategy interface)::

    import pandas as pd
    s = TripleEMAStrategy(symbol="NIFTY", capital=100000.0)
    signals = s.generate_signals(df)  # pd.Series of 1/-1/0

Registry key: ``triple_ema``
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Deque

import pandas as pd

from core.logger import logger

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_FAST    = 9
_DEFAULT_MEDIUM  = 21
_DEFAULT_SLOW    = 55
_DEFAULT_POS_PCT = 0.95

# Retain 3× slow period for warm-up safety
_MAX_HISTORY = 180


class TripleEMAStrategy:
    """Triple EMA crossover strategy compatible with StrategyRunner.

    Three EMAs must align in the same direction before a signal fires:
      BUY  : fast > medium > slow  AND  fast crosses above medium this bar
      SELL : fast < medium < slow  AND  fast crosses below medium this bar

    Attributes:
        symbol:        Trading symbol, e.g. "RELIANCE"
        capital:       Allocated capital in INR
        fast_period:   EMA fast window   (default  9)
        medium_period: EMA medium window (default 21)
        slow_period:   EMA slow window   (default 55)
    """

    #: Registry key — used by strategies/registry.py
    STRATEGY_ID = "triple_ema"

    def __init__(
        self,
        symbol: str,
        capital: float,
        params: dict | None = None,
    ) -> None:
        p = params or {}
        self.symbol        = symbol
        self.capital       = capital
        self.fast_period   = int(p.get("fast_period",   _DEFAULT_FAST))
        self.medium_period = int(p.get("medium_period", _DEFAULT_MEDIUM))
        self.slow_period   = int(p.get("slow_period",   _DEFAULT_SLOW))
        self.max_pos_pct   = float(p.get("max_position_pct", _DEFAULT_POS_PCT))

        if not (self.fast_period < self.medium_period < self.slow_period):
            raise ValueError(
                f"Periods must satisfy fast < medium < slow. "
                f"Got fast={self.fast_period}, medium={self.medium_period}, "
                f"slow={self.slow_period}"
            )

        # Rolling close price history
        self._closes: Deque[float] = deque(maxlen=_MAX_HISTORY)

        # EMA state — current and previous bar values
        self._ema_fast:   float | None = None
        self._ema_medium: float | None = None
        self._ema_slow:   float | None = None

        self._prev_ema_fast:   float | None = None
        self._prev_ema_medium: float | None = None

        # Position tracking: +qty = long, -qty = short, 0 = flat
        self._position: int = 0

        # EMA multipliers (cached)
        self._k_fast   = 2.0 / (self.fast_period   + 1)
        self._k_medium = 2.0 / (self.medium_period + 1)
        self._k_slow   = 2.0 / (self.slow_period   + 1)

        logger.info(
            f"[TripleEMA] Initialised: {symbol}  capital={capital:,.0f}  "
            f"fast={self.fast_period}  medium={self.medium_period}  slow={self.slow_period}"
        )

    # ------------------------------------------------------------------
    # Core method — called by StrategyRunner._tick()
    # ------------------------------------------------------------------

    def on_bar(self, bar: dict[str, Any]) -> dict | None:
        """Process a new OHLCV bar and return a signal dict or None.

        Args:
            bar: OHLCV dict with at least a ``close`` key.

        Returns:
            ``{"side": "BUY"|"SELL", "qty": int}`` on aligned crossover, else ``None``.
        """
        close = float(bar.get("close", 0.0))
        if close <= 0:
            logger.warning(f"[TripleEMA:{self.symbol}] Invalid close={close}, skipping bar.")
            return None

        self._closes.append(close)

        # Snapshot previous EMA values before this bar's update
        self._prev_ema_fast   = self._ema_fast
        self._prev_ema_medium = self._ema_medium

        # Update all three EMAs
        self._ema_fast   = self._update_ema(close, self._ema_fast,   self._k_fast,   self.fast_period)
        self._ema_medium = self._update_ema(close, self._ema_medium, self._k_medium, self.medium_period)
        self._ema_slow   = self._update_ema(close, self._ema_slow,   self._k_slow,   self.slow_period)

        # Need at least slow_period bars before generating signals
        if len(self._closes) < self.slow_period:
            return None

        # Need previous values to detect crossover
        if self._prev_ema_fast is None or self._prev_ema_medium is None:
            return None

        return self._check_signal(close)

    # ------------------------------------------------------------------
    # Signal detection
    # ------------------------------------------------------------------

    def _check_signal(self, price: float) -> dict | None:
        """Return BUY/SELL signal when all three EMAs align and fast crosses medium."""
        fast   = self._ema_fast
        medium = self._ema_medium
        slow   = self._ema_slow
        pf     = self._prev_ema_fast
        pm     = self._prev_ema_medium

        if None in (fast, medium, slow, pf, pm):
            return None

        # Triple alignment + crossover conditions
        bullish_cross = (pf <= pm) and (fast > medium) and (fast > medium > slow)
        bearish_cross = (pf >= pm) and (fast < medium) and (fast < medium < slow)

        if bullish_cross and self._position <= 0:
            qty = self._calc_qty(price)
            if qty <= 0:
                logger.warning(f"[TripleEMA:{self.symbol}] BUY signal but qty=0 — insufficient capital.")
                return None
            logger.info(
                f"[TripleEMA:{self.symbol}] BUY  qty={qty}  "
                f"fast={fast:.4f}  medium={medium:.4f}  slow={slow:.4f}"
            )
            self._position = qty
            return {"side": "BUY", "qty": qty}

        if bearish_cross and self._position >= 0:
            qty = self._calc_qty(price)
            if qty <= 0:
                logger.warning(f"[TripleEMA:{self.symbol}] SELL signal but qty=0 — insufficient capital.")
                return None
            logger.info(
                f"[TripleEMA:{self.symbol}] SELL qty={qty}  "
                f"fast={fast:.4f}  medium={medium:.4f}  slow={slow:.4f}"
            )
            self._position = -qty
            return {"side": "SELL", "qty": qty}

        return None

    # ------------------------------------------------------------------
    # Backtesting interface (BaseStrategy-compatible)
    # ------------------------------------------------------------------

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Vectorised signal generation for backtesting.

        Args:
            df: DataFrame with a ``Close`` column (OHLCV, capital C).

        Returns:
            pd.Series of int: 1 (BUY), -1 (SELL), 0 (HOLD), aligned to df.index.
        """
        close = df["Close"].astype(float)

        ema_fast   = close.ewm(span=self.fast_period,   adjust=False).mean()
        ema_medium = close.ewm(span=self.medium_period, adjust=False).mean()
        ema_slow   = close.ewm(span=self.slow_period,   adjust=False).mean()

        # Triple alignment flags
        bullish = (ema_fast > ema_medium) & (ema_medium > ema_slow)
        bearish = (ema_fast < ema_medium) & (ema_medium < ema_slow)

        # Crossover detection (fast vs medium)
        crossed_above = (ema_fast.shift(1) <= ema_medium.shift(1)) & (ema_fast > ema_medium)
        crossed_below = (ema_fast.shift(1) >= ema_medium.shift(1)) & (ema_fast < ema_medium)

        signals = pd.Series(0, index=df.index, dtype=int)
        signals[bullish & crossed_above] =  1
        signals[bearish & crossed_below] = -1

        # Zero out warm-up period
        signals.iloc[: self.slow_period] = 0

        return signals

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _update_ema(price: float, prev_ema: float | None, k: float, period: int) -> float:
        """Incremental EMA update. Seeds with first available price."""
        if prev_ema is None:
            return price
        return price * k + prev_ema * (1 - k)

    def _calc_qty(self, price: float) -> int:
        """Calculate position size in shares."""
        if price <= 0:
            return 0
        return math.floor(self.capital * self.max_pos_pct / price)

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        """Return current indicator state — useful for dashboard display."""
        return {
            "symbol":     self.symbol,
            "strategy":   self.STRATEGY_ID,
            "fast_ema":   round(self._ema_fast,   4) if self._ema_fast   is not None else None,
            "medium_ema": round(self._ema_medium, 4) if self._ema_medium is not None else None,
            "slow_ema":   round(self._ema_slow,   4) if self._ema_slow   is not None else None,
            "position":   self._position,
            "bars_seen":  len(self._closes),
            "params": {
                "fast_period":      self.fast_period,
                "medium_period":    self.medium_period,
                "slow_period":      self.slow_period,
                "max_position_pct": self.max_pos_pct,
            },
        }

    def __repr__(self) -> str:
        return (
            f"TripleEMAStrategy(symbol={self.symbol!r}, "
            f"fast={self.fast_period}, medium={self.medium_period}, slow={self.slow_period})"
        )
