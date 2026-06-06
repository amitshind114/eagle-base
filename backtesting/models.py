"""Canonical BacktestResult model — single source of truth.

All consumers (engine, metrics, API, tests) must import from here.
backtesting/result.py is an alias that re-exports from this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict


# ── Trade ────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    """A single completed round-trip trade (entry + exit)."""

    symbol: str
    direction: str          # 'LONG'
    entry_date: Any         # pd.Timestamp or str
    exit_date: Any          # pd.Timestamp or str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float              # Absolute net PnL (after charges)
    pnl_pct: float          # PnL as percentage of entry cost
    exit_reason: str = ""   # 'SIGNAL' | 'END_OF_DATA'

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0


# ── BacktestResult ───────────────────────────────────────────────────────

class BacktestResult(BaseModel):
    """Complete result of a BacktestEngine.run() call.

    Fields:
        symbol           — instrument symbol
        strategy_name    — strategy class name
        trades           — list of Trade objects (one per round-trip)
        equity_curve     — per-bar portfolio value as pd.Series
        buy_hold_curve   — buy-and-hold reference as pd.Series
        drawdown_series  — per-bar drawdown fraction as pd.Series (negative)
        total_return_pct — strategy net return %
        buy_hold_return_pct — B&H return % over same period
        sharpe_ratio     — annualised Sharpe (252-day)
        max_drawdown_pct — maximum peak-to-trough drawdown % (NEGATIVE)
        win_rate_pct     — % of trades that were profitable
        total_trades     — total number of completed round-trips
        profit_factor    — gross profit / gross loss (999.0 if no losses)
        avg_win_pct      — average winning trade return %
        avg_loss_pct     — average losing trade return %
        final_capital    — ending portfolio value in INR
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Identification
    symbol: str = ""
    strategy_name: str = ""

    # Trade log
    trades: list = field(default_factory=list)  # list[Trade]

    # Curves
    equity_curve: pd.Series = None          # type: ignore[assignment]
    buy_hold_curve: pd.Series = None        # type: ignore[assignment]
    drawdown_series: pd.Series = None       # type: ignore[assignment]

    # Scalar metrics
    total_return_pct: float = 0.0
    buy_hold_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0           # NEGATIVE convention
    win_rate_pct: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    final_capital: float = 0.0

    # ── Convenience helpers (mirror legacy result.py API) ────────────────

    @property
    def win_rate(self) -> float:
        """Alias for win_rate_pct (legacy compat)."""
        return self.win_rate_pct

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.is_winner)

    @property
    def losing_trades(self) -> int:
        return self.total_trades - self.winning_trades

    def summary(self) -> str:
        lines = [
            f"{'='*52}",
            f" Backtest : {self.strategy_name} on {self.symbol}",
            f"{'='*52}",
            f" Initial Capital    : ₹{self.final_capital - self.total_pnl:,.0f}",
            f" Final Capital      : ₹{self.final_capital:,.0f}",
            f" Total Return       : {self.total_return_pct:.2f}%",
            f" Buy & Hold Return  : {self.buy_hold_return_pct:.2f}%",
            f" Sharpe Ratio       : {self.sharpe_ratio:.3f}",
            f" Max Drawdown       : {self.max_drawdown_pct:.2f}%",
            f" Win Rate           : {self.win_rate_pct:.1f}%",
            f" Total Trades       : {self.total_trades}",
            f" Profit Factor      : {self.profit_factor:.4f}",
            f" Avg Win            : {self.avg_win_pct:.3f}%",
            f" Avg Loss           : {self.avg_loss_pct:.3f}%",
            f"{'='*52}",
        ]
        return "\n".join(lines)

    def to_trades_df(self) -> pd.DataFrame:
        """Return trades as a DataFrame for analysis."""
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "symbol":       t.symbol,
                "direction":    t.direction,
                "entry_date":   t.entry_date,
                "exit_date":    t.exit_date,
                "entry_price":  t.entry_price,
                "exit_price":   t.exit_price,
                "quantity":     t.quantity,
                "pnl":          t.pnl,
                "pnl_pct":      t.pnl_pct,
                "exit_reason":  t.exit_reason,
                "winner":       t.is_winner,
            }
            for t in self.trades
        ])

    def to_equity_df(self) -> pd.DataFrame:
        """Return equity curve as a DataFrame."""
        if self.equity_curve is None:
            return pd.DataFrame()
        return pd.DataFrame({"equity": self.equity_curve})
