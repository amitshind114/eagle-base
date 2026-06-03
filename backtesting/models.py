"""Backtest result model."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict


class BacktestResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    equity_curve: pd.Series
    buy_hold_curve: pd.Series
    drawdown_series: pd.Series
    total_return_pct: float
    buy_hold_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    profit_factor: float
    avg_win_pct: float
    avg_loss_pct: float
    final_capital: float
