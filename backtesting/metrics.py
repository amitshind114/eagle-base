"""Metrics Calculator — Priority 3.

Computes key performance metrics from equity curve and trades.

Metrics:
    Sharpe Ratio, Sortino Ratio, Max Drawdown,
    CAGR, Calmar Ratio, Win Rate, Profit Factor
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from backtesting.result import BacktestResult

TRADING_DAYS = 252
RISK_FREE_RATE = 0.065  # 6.5% India risk-free rate


class MetricsCalculator:
    """Calculates performance metrics from a BacktestResult."""

    def compute(self, result: "BacktestResult") -> dict:
        """Compute all metrics. Returns dict of metric name → value."""
        if not result.equity_curve or len(result.equity_curve) < 2:
            return {"error": "Insufficient equity curve data"}

        equity = np.array(result.equity_curve, dtype=float)
        returns = np.diff(equity) / equity[:-1]

        metrics = {}
        metrics["sharpe_ratio"]    = self._sharpe(returns)
        metrics["sortino_ratio"]   = self._sortino(returns)
        metrics["max_drawdown_pct"]= self._max_drawdown(equity)
        metrics["cagr_pct"]        = self._cagr(equity, len(equity))
        metrics["calmar_ratio"]    = self._calmar(metrics["cagr_pct"], metrics["max_drawdown_pct"])
        metrics["profit_factor"]   = self._profit_factor(result.trades)
        metrics["avg_trade_pnl"]   = self._avg_trade(result.trades)
        metrics["expectancy"]      = self._expectancy(result.trades)
        return metrics

    def _sharpe(self, returns: np.ndarray) -> float:
        daily_rf = RISK_FREE_RATE / TRADING_DAYS
        excess = returns - daily_rf
        std = np.std(excess)
        if std == 0:
            return 0.0
        return float(np.mean(excess) / std * math.sqrt(TRADING_DAYS))

    def _sortino(self, returns: np.ndarray) -> float:
        daily_rf = RISK_FREE_RATE / TRADING_DAYS
        excess = returns - daily_rf
        downside = excess[excess < 0]
        if len(downside) == 0:
            return 0.0
        downside_std = np.std(downside)
        if downside_std == 0:
            return 0.0
        return float(np.mean(excess) / downside_std * math.sqrt(TRADING_DAYS))

    def _max_drawdown(self, equity: np.ndarray) -> float:
        """Returns max drawdown as a positive percentage."""
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        return float(np.max(drawdown) * 100)

    def _cagr(self, equity: np.ndarray, n_days: int) -> float:
        """Compound Annual Growth Rate as percentage."""
        if equity[0] == 0 or n_days == 0:
            return 0.0
        years = n_days / TRADING_DAYS
        if years == 0:
            return 0.0
        return float(((equity[-1] / equity[0]) ** (1 / years) - 1) * 100)

    def _calmar(self, cagr_pct: float, max_dd_pct: float) -> float:
        if max_dd_pct == 0:
            return 0.0
        return float(cagr_pct / max_dd_pct)

    def _profit_factor(self, trades) -> float:
        gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss   = abs(sum(t.pnl for t in trades if t.pnl < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return float(gross_profit / gross_loss)

    def _avg_trade(self, trades) -> float:
        if not trades:
            return 0.0
        return float(sum(t.pnl for t in trades) / len(trades))

    def _expectancy(self, trades) -> float:
        """Average PnL per trade weighted by win/loss rate."""
        if not trades:
            return 0.0
        winners = [t.pnl for t in trades if t.pnl > 0]
        losers  = [t.pnl for t in trades if t.pnl <= 0]
        win_rate  = len(winners) / len(trades)
        loss_rate = len(losers)  / len(trades)
        avg_win  = sum(winners) / len(winners) if winners else 0.0
        avg_loss = sum(losers)  / len(losers)  if losers  else 0.0
        return float(win_rate * avg_win + loss_rate * avg_loss)
