"""Backtest Runner — Phase 02/03 updated.

High-level interface that wires DataManager + BacktestEngine + Strategy.
Use this as the single entry point for running backtests.

Changes in Phase 03:
  - interval is now passed to BacktestEngine so Sharpe uses correct
    annualisation periods (PERIODS dict).  Previously interval was stored
    on the runner but never forwarded to the engine — causing every
    non-daily backtest to use np.sqrt(252) regardless of timeframe.
  - product_type param added and forwarded to engine for correct STT.

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
        product_type: str = "CNC",
        data: Optional[pd.DataFrame] = None,
    ):
        self.strategy       = strategy
        self.symbol         = symbol
        self.from_date      = from_date
        self.to_date        = to_date
        self.interval       = interval
        self.capital        = capital
        self.commission_pct = commission_pct
        self.slippage_pct   = slippage_pct
        self.product_type   = product_type
        self._data          = data  # Pre-loaded data (optional)

    def run(self) -> "BacktestResult":
        """Fetch data (if needed) and run backtest.

        Returns:
            BacktestResult with trades, equity curve, metrics.

        Phase 03 fix: interval and product_type are now forwarded to
        BacktestEngine so Sharpe annualisation and STT are correct.
        """
        df = self._load_data()
        if df.empty:
            raise ValueError(f"No data for {self.symbol} [{self.from_date} → {self.to_date}]")

        engine = BacktestEngine(
            symbol=self.symbol,
            initial_capital=self.capital,
            commission_pct=self.commission_pct,
            slippage_pct=self.slippage_pct,
            interval=self.interval,       # FIX: was not forwarded — broke Sharpe on intraday
            product_type=self.product_type,  # FIX: was not forwarded — wrong STT for delivery
        )
        result = engine.run(df, self.strategy)

        # Phase 03: update strategy metadata with realised win/loss metrics
        # so sized_qty() has accurate inputs next time it is called.
        # avg_win_pct and avg_loss_pct from BacktestResult are already
        # expressed as fraction-of-trade (e.g. 0.04 = 4%), not % of capital.
        # Pass them directly to sizer — no conversion needed.
        try:
            m = self.strategy.metadata()
            if not m:  # strategy hasn't overridden metadata() — update dynamically
                if result.total_trades > 0:
                    self.strategy._realised_win_rate   = result.win_rate_pct / 100.0
                    self.strategy._realised_avg_win    = result.avg_win_pct   # already decimal
                    self.strategy._realised_avg_loss   = result.avg_loss_pct  # already decimal
        except Exception:
            pass  # non-critical — sizer falls back to defaults

        return result

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
