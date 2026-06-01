"""Backtest Runner — Priority 3.

High-level interface that wires DataManager + BacktestEngine + Strategy.
Use this as the single entry point for running backtests.

Usage:
    from backtesting.runner import BacktestRunner
    from strategies.sma_crossover import SMACrossoverStrategy

    runner = BacktestRunner(
        symbol="RELIANCE.NS",
        strategy=SMACrossoverStrategy(fast=20, slow=50),
        from_date="2023-01-01",
        to_date="2024-12-31",
        capital=100000,
    )
    result = runner.run()
    print(result.summary())
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import pandas as pd

from backtesting.engine import BacktestEngine
from core.logger import logger

if TYPE_CHECKING:
    from backtesting.result import BacktestResult
    from strategies.base import BaseStrategy


class BacktestRunner:
    """Wires DataManager + BacktestEngine + Strategy into one clean run."""

    def __init__(
        self,
        strategy: "BaseStrategy",
        symbol: str = "RELIANCE.NS",
        from_date: str = "2023-01-01",
        to_date: str = "2024-12-31",
        interval: str = "1d",
        capital: float = 100_000.0,
        commission_pct: float = 0.0003,
        slippage_pct: float = 0.0001,
        data: Optional[pd.DataFrame] = None,
    ):
        self.strategy = strategy
        self.symbol = symbol
        self.from_date = from_date
        self.to_date = to_date
        self.interval = interval
        self.capital = capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self._data = data  # Pre-loaded data (optional)

    def run(self) -> "BacktestResult":
        """Fetch data (if needed) and run backtest.

        Returns:
            BacktestResult with trades, equity curve, metrics
        """
        df = self._load_data()
        if df.empty:
            raise ValueError(f"No data for {self.symbol} [{self.from_date} → {self.to_date}]")

        engine = BacktestEngine(
            symbol=self.symbol,
            initial_capital=self.capital,
            commission_pct=self.commission_pct,
            slippage_pct=self.slippage_pct,
        )
        return engine.run(df, self.strategy)

    def _load_data(self) -> pd.DataFrame:
        if self._data is not None:
            return self._data
        try:
            from data.manager import DataManager
            manager = DataManager()
            logger.info(f"[runner] Fetching {self.symbol} {self.interval} {self.from_date}→{self.to_date}")
            return manager.get_ohlcv(self.symbol, self.interval, self.from_date, self.to_date)
        except Exception as e:
            logger.error(f"[runner] Data fetch failed: {e}")
            return pd.DataFrame()
