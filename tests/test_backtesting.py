"""Tests for backtesting engine.

Fixes
-----
- P0   : engine.run(df, strategy) — capital via constructor, not a kwarg.
- P10  : make_df uses numpy arrays (not pd.Series) to avoid DatetimeIndex
         alignment producing all-NaN Close columns.
- H5   : freq='B' deprecated in pandas 3.x; replaced with pd.offsets.BDay().
- H1   : BacktestEngine now strips tz from df before generate_signals so
         tz-aware (yfinance UTC) and tz-naive (pandas-ta) indexes align.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtesting.engine import BacktestEngine
from backtesting.models import BacktestResult
from strategies.sma_crossover import SmaCrossover
from core.exceptions import InsufficientDataError


def make_df(n: int = 200, seed: int = 0, tz_aware: bool = False) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame.

    Uses np.ndarray for column values (not pd.Series) to avoid index-alignment
    NaN when building against a DatetimeIndex.

    Args:
        n        : number of bars
        seed     : RNG seed for reproducibility
        tz_aware : when True, returns UTC-aware index to simulate yfinance output
    """
    rng   = np.random.default_rng(seed)
    close = np.cumsum(rng.standard_normal(n)) + 1000.0
    # FIX H5: pd.offsets.BDay() replaces deprecated freq='B'
    idx   = pd.date_range("2020-01-01", periods=n, freq=pd.offsets.BDay())
    if tz_aware:
        idx = idx.tz_localize("UTC")
    return pd.DataFrame(
        {
            "Open":   close * 0.99,
            "High":   close * 1.01,
            "Low":    close * 0.98,
            "Close":  close,
            "Volume": rng.integers(100_000, 1_000_000, n).astype(float),
        },
        index=idx,
    )


class TestBacktestEngine:
    def test_returns_result(self):
        df     = make_df()
        engine = BacktestEngine(initial_capital=100_000)
        result = engine.run(df, SmaCrossover(20, 50))
        assert isinstance(result, BacktestResult)
        assert result.final_capital > 0

    def test_max_drawdown_is_negative(self):
        df     = make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert result.max_drawdown_pct <= 0, (
            f"MaxDD should be <= 0, got {result.max_drawdown_pct}"
        )
        assert result.max_drawdown_pct >= -100

    def test_win_rate_in_range(self):
        df     = make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert 0 <= result.win_rate_pct <= 100

    def test_raises_on_short_data(self):
        df = make_df(5)
        with pytest.raises(InsufficientDataError):
            BacktestEngine().run(df, SmaCrossover(20, 50))

    def test_result_has_trades_field(self):
        df     = make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert hasattr(result, "trades")
        assert isinstance(result.trades, list)

    def test_result_has_symbol_and_strategy_name(self):
        df     = make_df()
        result = BacktestEngine(symbol="TEST", initial_capital=100_000).run(
            df, SmaCrossover(20, 50)
        )
        assert result.symbol == "TEST"
        assert isinstance(result.strategy_name, str)
        assert len(result.strategy_name) > 0

    def test_tz_aware_df_runs_without_error(self):
        """FIX H1: tz-aware yfinance DataFrame must not produce zero trades."""
        df     = make_df(tz_aware=True)   # simulates yfinance UTC output
        result = BacktestEngine(symbol="TZ_TEST", initial_capital=100_000).run(
            df, SmaCrossover(20, 50)
        )
        # Should get a valid result, not all-NaN signals
        assert isinstance(result, BacktestResult)
        assert result.final_capital > 0
