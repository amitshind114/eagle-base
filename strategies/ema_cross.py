"""EMA Crossover Strategy — Eagle-Base reference implementation.

Signal logic:
  - Fast EMA (default 9) crosses above Slow EMA (default 21) → BUY
  - Fast EMA crosses below Slow EMA                           → SELL
  - No signal while EMAs are flat (no crossover this bar)     → None

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

    strategy = EMACrossStrategy(
        symbol="RELIANCE",
        capital=50000.0,
        params={"fast_period": 9, "slow_period": 21},
    )
    signal = strategy.on_bar(bar)  # {"side": "BUY", "qty": 15} or None

Registry key: ``ema_cross``
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Deque

from core.logger import logger

# Default periods
_DEFAULT_FAST   = 9
_DEFAULT_SLOW   = 21
_DEFAULT_POS_PCT = 0.95

# Maximum bars to retain in history (2× slow period is enough)
_MAX_HISTORY = 60


class EMACrossStrategy:
    """EMA crossover strategy compatible with StrategyRunner.

    Attributes:
        symbol:      Trading symbol, e.g. "RELIANCE"
        capital:     Allocated capital in INR
        fast_period: EMA fast window (default 9)
        slow_period: EMA slow window (default 21)
    """

    #: Registry key — used by strategies/registry.py
    STRATEGY_ID = "ema_cross"

    def __init__(
        self,
        symbol: str,
        capital: float,
        params: dict | None = None,
    ) -> None:
        p = params or {}
        self.symbol      = symbol
        self.capital     = capital
        self.fast_period = int(p.get("fast_period", _DEFAULT_FAST))
        self.slow_period = int(p.get("slow_period", _DEFAULT_SLOW))
        self.max_pos_pct = float(p.get("max_position_pct", _DEFAULT_POS_PCT))

        if self.fast_period >= self.slow_period:
            raise ValueError(
                f"fast_period ({self.fast_period}) must be < slow_period ({self.slow_period})"
            )

        # Rolling close price history
        self._closes: Deque[float] = deque(maxlen=_MAX_HISTORY)

        # EMA state
        self._ema_fast: float | None = None
        self._ema_slow: float | None = None
        self._prev_ema_fast: float | None = None
        self._prev_ema_slow: float | None = None

        # Position tracking
        self._position: int = 0   # +qty = long, -qty = short, 0 = flat

        # Multipliers (cached)
        self._k_fast = 2.0 / (self.fast_period + 1)
        self._k_slow = 2.0 / (self.slow_period + 1)

        logger.info(
            f"[EMACross] Initialised: {symbol}  capital={capital:,.0f}  "
            f"fast={self.fast_period}  slow={self.slow_period}"
        )

    # ------------------------------------------------------------------
    # Core method — called by StrategyRunner._tick()
    # ------------------------------------------------------------------

    def on_bar(self, bar: dict[str, Any]) -> dict | None:
        """Process a new OHLCV bar and return a signal dict or None.

        Args:
            bar: OHLCV dict with at least a ``close`` key.

        Returns:
            ``{"side": "BUY"|"SELL", "qty": int}`` on crossover, else ``None``.
        """
        close = float(bar.get("close", 0.0))
        if close <= 0:
            logger.warning(f"[EMACross:{self.symbol}] Invalid close={close}, skipping bar.")
            return None

        self._closes.append(close)

        # Save previous EMA values before update
        self._prev_ema_fast = self._ema_fast
        self._prev_ema_slow = self._ema_slow

        # Update EMAs
        self._ema_fast = self._update_ema(close, self._ema_fast, self._k_fast, self.fast_period)
        self._ema_slow = self._update_ema(close, self._ema_slow, self._k_slow, self.slow_period)

        # Need at least slow_period bars before generating signals
        if len(self._closes) < self.slow_period:
            return None

        # Need previous values to detect crossover
        if self._prev_ema_fast is None or self._prev_ema_slow is None:
            return None

        return self._check_crossover(close)

    # ------------------------------------------------------------------
    # Signal detection
    # ------------------------------------------------------------------

    def _check_crossover(self, price: float) -> dict | None:
        """Return BUY/SELL signal on EMA crossover, or None."""
        fast_now  = self._ema_fast
        slow_now  = self._ema_slow
        fast_prev = self._prev_ema_fast
        slow_prev = self._prev_ema_slow

        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return None

        crossed_above = (fast_prev <= slow_prev) and (fast_now > slow_now)
        crossed_below = (fast_prev >= slow_prev) and (fast_now < slow_now)

        if crossed_above and self._position <= 0:
            qty = self._calc_qty(price)
            if qty <= 0:
                logger.warning(f"[EMACross:{self.symbol}] BUY signal but qty=0 — insufficient capital.")
                return None
            logger.info(f"[EMACross:{self.symbol}] BUY signal  qty={qty}  fast={fast_now:.4f}  slow={slow_now:.4f}")
            self._position = qty
            return {"side": "BUY", "qty": qty}

        elif crossed_below and self._position >= 0:
            qty = self._calc_qty(price)
            if qty <= 0:
                logger.warning(f"[EMACross:{self.symbol}] SELL signal but qty=0 — insufficient capital.")
                return None
            logger.info(f"[EMACross:{self.symbol}] SELL signal  qty={qty}  fast={fast_now:.4f}  slow={slow_now:.4f}")
            self._position = -qty
            return {"side": "SELL", "qty": qty}

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _update_ema(price: float, prev_ema: float | None, k: float, period: int) -> float:
        """Incremental EMA update. SMA-seed on first call."""
        if prev_ema is None:
            return price  # seed with first available price
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
            "symbol":    self.symbol,
            "strategy":  self.STRATEGY_ID,
            "fast_ema":  round(self._ema_fast, 4) if self._ema_fast else None,
            "slow_ema":  round(self._ema_slow, 4) if self._ema_slow else None,
            "position":  self._position,
            "bars_seen": len(self._closes),
            "params": {
                "fast_period":      self.fast_period,
                "slow_period":      self.slow_period,
                "max_position_pct": self.max_pos_pct,
            },
        }
