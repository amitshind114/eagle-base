"""Backtesting Engine — Priority 3.

Core event-driven backtesting engine.

TODO (Phase 4 - Priority 3):
- Implement run() with event loop
- Implement order simulation with slippage
- Implement commission model
- Produce BacktestResult with metrics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.logger import logger


@dataclass
class BacktestResult:
    """Result of a single backtest run."""

    strategy_name: str
    symbol: str
    from_date: str
    to_date: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    trade_log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades * 100


class BacktestEngine:
    """Core backtesting engine."""

    def __init__(self, data_provider=None, commission: float = 0.0003):
        self.data_provider = data_provider
        self.commission = commission

    def run(
        self,
        strategy,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> BacktestResult:
        """Run a backtest. TODO: Phase 4 Priority 3."""
        logger.info(f"Backtest run: {strategy.name} on {symbol}")
        raise NotImplementedError("TODO: Phase 4 Priority 3 — implement backtest engine run()")
