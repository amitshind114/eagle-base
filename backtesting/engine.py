"""Core backtesting engine — runs strategies on historical OHLCV data."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.exceptions import BacktestError, InsufficientDataError
from core.logger import get_logger
from .models import BacktestResult

log = get_logger("backtesting.engine")


class BacktestEngine:
    """Run a signal series against historical price data."""

    def run(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        capital: float = 100_000.0,
        commission_pct: float = 0.03,
    ) -> BacktestResult:
        """
        Run backtest.

        Args:
            df: OHLCV DataFrame indexed by datetime.
            signals: Series of 1 (long), -1 (short), 0 (flat) aligned to df.
            capital: Starting capital in INR.
            commission_pct: Commission per trade as percentage.

        Returns:
            BacktestResult with full metrics.
        """
        if df.empty or len(df) < 10:
            raise InsufficientDataError("Need at least 10 bars to backtest")

        if len(signals) != len(df):
            raise BacktestError("signals length must match df length")

        df = df.copy()
        df["signal"] = signals.values
        df["returns"] = df["Close"].pct_change().fillna(0)
        df["strategy_returns"] = df["signal"].shift(1).fillna(0) * df["returns"]

        # Apply commission on signal changes
        signal_changes = df["signal"].diff().abs() > 0
        df.loc[signal_changes, "strategy_returns"] -= commission_pct / 100

        df["equity"] = capital * (1 + df["strategy_returns"]).cumprod()
        df["buy_hold"] = capital * (1 + df["returns"]).cumprod()
        df["drawdown"] = (df["equity"] / df["equity"].cummax()) - 1

        total_return = (df["equity"].iloc[-1] - capital) / capital * 100
        bh_return = (df["buy_hold"].iloc[-1] - capital) / capital * 100
        max_dd = float(df["drawdown"].min() * 100)
        std = df["strategy_returns"].std()
        sharpe = (
            float(df["strategy_returns"].mean() / std * np.sqrt(252))
            if std > 0 else 0.0
        )
        wins = int((df["strategy_returns"] > 0).sum())
        losses = int((df["strategy_returns"] < 0).sum())
        total_trades = wins + losses
        win_rate = wins / total_trades * 100 if total_trades > 0 else 0.0
        avg_win = float(df.loc[df["strategy_returns"] > 0, "strategy_returns"].mean() * 100) if wins > 0 else 0.0
        avg_loss = float(df.loc[df["strategy_returns"] < 0, "strategy_returns"].mean() * 100) if losses > 0 else 0.0
        profit_factor = abs(avg_win * wins / (avg_loss * losses)) if avg_loss != 0 and losses > 0 else 0.0

        log.info(
            f"Backtest done | Return={total_return:.1f}% Sharpe={sharpe:.2f} MaxDD={max_dd:.1f}% WR={win_rate:.1f}%"
        )

        return BacktestResult(
            equity_curve=df["equity"],
            buy_hold_curve=df["buy_hold"],
            drawdown_series=df["drawdown"],
            total_return_pct=round(total_return, 2),
            buy_hold_return_pct=round(bh_return, 2),
            sharpe_ratio=round(sharpe, 3),
            max_drawdown_pct=round(max_dd, 2),
            win_rate_pct=round(win_rate, 2),
            total_trades=total_trades,
            profit_factor=round(profit_factor, 3),
            avg_win_pct=round(avg_win, 3),
            avg_loss_pct=round(avg_loss, 3),
            final_capital=round(float(df["equity"].iloc[-1]), 2),
        )
