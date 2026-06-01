"""Backtesting Metrics — Priority 3.

Calculates standard performance metrics from trade log and equity curve.

TODO (Phase 4 - Priority 3):
- Sharpe ratio
- Sortino ratio
- Max drawdown
- CAGR
- Win rate, profit factor
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class MetricsCalculator:
    """Calculates performance metrics from backtest results."""

    @staticmethod
    def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.065) -> float:
        """Calculate annualized Sharpe ratio. TODO: Phase 4 Priority 3."""
        raise NotImplementedError("TODO: Phase 4 Priority 3")

    @staticmethod
    def max_drawdown(equity_curve: list[float]) -> float:
        """Calculate maximum drawdown percentage. TODO: Phase 4 Priority 3."""
        raise NotImplementedError("TODO: Phase 4 Priority 3")

    @staticmethod
    def win_rate(trade_log: list[dict]) -> float:
        """Calculate win rate from trade log. TODO: Phase 4 Priority 3."""
        raise NotImplementedError("TODO: Phase 4 Priority 3")
