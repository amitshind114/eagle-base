"""Report generator — computes PnL, metrics, trade statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.logger import get_logger

log = get_logger("reporting.generator")


class ReportGenerator:
    """Generate performance reports from trade logs."""

    def summary(self, trades: pd.DataFrame, initial_capital: float = 500_000.0) -> dict:
        """
        Compute summary statistics from a trade log.

        Args:
            trades: DataFrame with columns [Date, Symbol, Side, Qty, PnL, Strategy].
            initial_capital: Starting capital.

        Returns:
            Dict of performance metrics.
        """
        if trades.empty:
            return {}

        total_pnl = trades["PnL"].sum()
        win_trades = (trades["PnL"] > 0).sum()
        loss_trades = (trades["PnL"] <= 0).sum()
        total_trades = len(trades)
        win_rate = win_trades / total_trades * 100 if total_trades > 0 else 0.0
        avg_win = trades.loc[trades["PnL"] > 0, "PnL"].mean() if win_trades > 0 else 0.0
        avg_loss = trades.loc[trades["PnL"] < 0, "PnL"].mean() if loss_trades > 0 else 0.0
        profit_factor = abs(avg_win * win_trades / (avg_loss * loss_trades)) if avg_loss != 0 and loss_trades > 0 else 0.0
        max_win = trades["PnL"].max()
        max_loss = trades["PnL"].min()
        cum_pnl = trades["PnL"].cumsum()
        equity = initial_capital + cum_pnl
        max_dd = float(((equity / equity.cummax()) - 1).min() * 100)

        log.info(f"Report: PnL=₹{total_pnl:,.0f} WR={win_rate:.1f}% Trades={total_trades}")

        return {
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_pnl / initial_capital * 100, 2),
            "win_trades": int(win_trades),
            "loss_trades": int(loss_trades),
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 3),
            "max_win": round(max_win, 2),
            "max_loss": round(max_loss, 2),
            "max_drawdown_pct": round(max_dd, 2),
        }

    def by_strategy(self, trades: pd.DataFrame) -> pd.DataFrame:
        """Group PnL and win rate by strategy."""
        if trades.empty or "Strategy" not in trades.columns:
            return pd.DataFrame()
        grp = trades.groupby("Strategy").agg(
            total_pnl=("PnL", "sum"),
            trades=("PnL", "count"),
            avg_pnl=("PnL", "mean"),
            wins=("PnL", lambda x: (x > 0).sum()),
        ).reset_index()
        grp["win_rate_pct"] = grp["wins"] / grp["trades"] * 100
        return grp.round(2)
