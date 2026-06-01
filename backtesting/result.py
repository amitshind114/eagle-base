"""Backtest Result — Priority 3.

Stores all trades, equity curve, and computed metrics
from a completed backtest run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Trade:
    """A single completed trade (entry + exit)."""

    symbol: str
    direction: str          # 'LONG' or 'SHORT'
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float              # Absolute PnL
    pnl_pct: float          # PnL as percentage
    exit_reason: str = ""   # 'SIGNAL', 'STOP_LOSS', 'TARGET', 'END_OF_DATA'

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0


@dataclass
class BacktestResult:
    """Complete result of a backtest run."""

    symbol: str
    strategy_name: str
    initial_capital: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def final_capital(self) -> float:
        return self.equity_curve[-1] if self.equity_curve else self.initial_capital

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def total_return_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return (self.final_capital - self.initial_capital) / self.initial_capital * 100

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.is_winner)

    @property
    def losing_trades(self) -> int:
        return self.total_trades - self.winning_trades

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades * 100

    def summary(self) -> str:
        lines = [
            f"{'='*50}",
            f" Backtest: {self.strategy_name} on {self.symbol}",
            f"{'='*50}",
            f" Initial Capital : ₹{self.initial_capital:,.0f}",
            f" Final Capital   : ₹{self.final_capital:,.0f}",
            f" Total PnL       : ₹{self.total_pnl:,.2f}",
            f" Total Return    : {self.total_return_pct:.2f}%",
            f" Total Trades    : {self.total_trades}",
            f" Win Rate        : {self.win_rate:.1f}%",
            f" Winning Trades  : {self.winning_trades}",
            f" Losing Trades   : {self.losing_trades}",
        ]
        for k, v in self.metrics.items():
            if isinstance(v, float):
                lines.append(f" {k:<16} : {v:.4f}")
            else:
                lines.append(f" {k:<16} : {v}")
        lines.append(f"{'='*50}")
        return "\n".join(lines)

    def to_trades_df(self) -> pd.DataFrame:
        """Return trades as a DataFrame for analysis."""
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "symbol": t.symbol,
                "direction": t.direction,
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "exit_reason": t.exit_reason,
                "winner": t.is_winner,
            }
            for t in self.trades
        ])

    def to_equity_df(self) -> pd.DataFrame:
        """Return equity curve as a DataFrame."""
        return pd.DataFrame({"equity": self.equity_curve})
