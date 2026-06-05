"""Daily risk limits — stateful tracker for the current trading session.

Tracks trades placed, PnL accumulated, and drawdown from equity peak.
Any module that wants to know whether trading is still allowed calls
`risk_limits.check()` — it raises RiskLimitBreached if a hard limit is hit.

Designed to be reset once per trading day (call `risk_limits.reset()` at
session start or when the scheduler fires the pre-market job).

Usage:
    from risk.limits import risk_limits, RiskLimitBreached

    try:
        risk_limits.check(symbol, side, qty, price)
    except RiskLimitBreached as exc:
        logger.warning(str(exc))
        return  # skip the order

    # order is safe — proceed
    risk_limits.record_trade(symbol, side, qty, price)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from threading import Lock
from typing import Literal


class RiskLimitBreached(Exception):
    """Raised when a hard risk limit would be violated by the proposed trade."""


@dataclass
class DailyState:
    """Mutable daily counters — reset each session."""
    trades_placed: int = 0
    realized_pnl: float = 0.0
    equity_peak: float = 0.0
    session_date: date = field(default_factory=date.today)


class RiskLimits:
    """Thread-safe daily risk limit enforcer."""

    def __init__(
        self,
        max_daily_loss: float | None = None,
        max_trades_per_day: int | None = None,
        max_position_pct: float = 0.10,
        max_drawdown_pct: float = 0.05,
        total_capital: float | None = None,
    ) -> None:
        self._lock = Lock()
        self._state = DailyState()

        cap = total_capital or float(os.environ.get("TOTAL_CAPITAL", "200000"))
        self.total_capital     = cap
        self.max_daily_loss    = max_daily_loss    or float(os.environ.get("MAX_DAILY_LOSS",    str(cap * 0.02)))
        self.max_trades_per_day = max_trades_per_day or int(os.environ.get("MAX_TRADES_PER_DAY", "20"))
        self.max_position_pct  = max_position_pct
        self.max_drawdown_pct  = max_drawdown_pct

    def reset(self, capital: float | None = None) -> None:
        """Call at session start.  Optionally update total capital."""
        with self._lock:
            if capital is not None:
                self.total_capital = capital
            self._state = DailyState(equity_peak=self.total_capital)

    def check(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: int,
        price: float,
    ) -> None:
        """Raise RiskLimitBreached if any hard limit would be violated.

        Call BEFORE placing any order.  Does not mutate state.
        """
        with self._lock:
            self._auto_reset_if_new_day()

            if self._state.trades_placed >= self.max_trades_per_day:
                raise RiskLimitBreached(
                    f"Max trades per day ({self.max_trades_per_day}) reached"
                )

            if self._state.realized_pnl <= -abs(self.max_daily_loss):
                raise RiskLimitBreached(
                    f"Daily loss cap ₹{self.max_daily_loss:,.0f} hit "
                    f"(current PnL ₹{self._state.realized_pnl:,.2f})"
                )

            if self.total_capital > 0:
                drawdown = (self._state.equity_peak - (self.total_capital + self._state.realized_pnl))
                drawdown_pct = drawdown / self._state.equity_peak if self._state.equity_peak else 0
                if drawdown_pct >= self.max_drawdown_pct:
                    raise RiskLimitBreached(
                        f"Max drawdown {self.max_drawdown_pct * 100:.1f}% breached "
                        f"(current {drawdown_pct * 100:.2f}%)"
                    )

            trade_value = qty * price
            if self.total_capital > 0 and trade_value / self.total_capital > self.max_position_pct:
                raise RiskLimitBreached(
                    f"Single position size {trade_value / self.total_capital * 100:.1f}% "
                    f"exceeds limit {self.max_position_pct * 100:.0f}%"
                )

    def record_trade(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: int,
        price: float,
        pnl: float = 0.0,
    ) -> None:
        """Call AFTER a fill is confirmed to update daily counters."""
        with self._lock:
            self._auto_reset_if_new_day()
            self._state.trades_placed += 1
            self._state.realized_pnl  += pnl
            current_equity = self.total_capital + self._state.realized_pnl
            if current_equity > self._state.equity_peak:
                self._state.equity_peak = current_equity

    def status(self) -> dict:
        """Return a snapshot of current daily state — safe to log or display."""
        with self._lock:
            return {
                "trades_placed":     self._state.trades_placed,
                "max_trades":        self.max_trades_per_day,
                "realized_pnl":      round(self._state.realized_pnl, 2),
                "max_daily_loss":    -abs(self.max_daily_loss),
                "equity_peak":       round(self._state.equity_peak, 2),
                "total_capital":     self.total_capital,
                "session_date":      self._state.session_date.isoformat(),
            }

    def _auto_reset_if_new_day(self) -> None:
        """Auto-reset counters if called on a new calendar day."""
        today = date.today()
        if self._state.session_date != today:
            self._state = DailyState(
                equity_peak=self.total_capital,
                session_date=today,
            )


# Module-level singleton — import and use directly
risk_limits = RiskLimits()
