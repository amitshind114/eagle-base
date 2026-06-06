"""Tests for backtesting engine.

FIX P0: Previous version called engine.run(df, signals, capital=...) which is
the wrong signature. engine.run() takes (df, strategy), not (df, signals, capital).
BacktestEngine(initial_capital=X) is how capital is set.

FIX P10: make_df used pd.Series for column values — pandas aligns by index,
causing all Close values to become NaN when df has a DatetimeIndex but the
Series has a RangeIndex. Fixed by using .values (ndarray) instead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtesting.engine import BacktestEngine
from backtesting.models import BacktestResult
from strategies.sma_crossover import SmaCrossover
from core.exceptions import InsufficientDataError


def make_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame with a proper DatetimeIndex.

    FIX: close must be a numpy array (not pd.Series) so that pandas
    does not attempt index-alignment when building the DataFrame.
    Using a pd.Series with RangeIndex against a DatetimeIndex causes
    all values to align as NaN.
    """
    rng   = np.random.default_rng(seed)
    close = np.cumsum(rng.standard_normal(n)) + 1000.0   # ndarray, always positive near 1000
    idx   = pd.date_range("2020-01-01", periods=n, freq="B")
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
        """FIX P0-001: engine.run() takes (df, strategy), capital via constructor."""
        df     = make_df()
        engine = BacktestEngine(initial_capital=100_000)
        result = engine.run(df, SmaCrossover(20, 50))
        assert isinstance(result, BacktestResult)
        assert result.final_capital > 0

    def test_max_drawdown_is_negative(self):
        """FIX P0-004: max_drawdown_pct must always be <= 0."""
        df     = make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert result.max_drawdown_pct <= 0, (
            f"MaxDD should be negative, got {result.max_drawdown_pct}"
        )
        assert result.max_drawdown_pct >= -100

    def test_win_rate_in_range(self):
        df     = make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert 0 <= result.win_rate_pct <= 100

    def test_raises_on_short_data(self):
        """FIX P0-001: short-data test also uses correct call signature."""
        df = make_df(5)
        with pytest.raises(InsufficientDataError):
            BacktestEngine().run(df, SmaCrossover(20, 50))

    def test_result_has_trades_field(self):
        """FIX P0-002: unified BacktestResult must expose .trades."""
        df     = make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert hasattr(result, "trades")
        assert isinstance(result.trades, list)

    def test_result_has_symbol_and_strategy_name(self):
        """FIX P0-002: unified BacktestResult must expose .symbol and .strategy_name."""
        df     = make_df()
        result = BacktestEngine(symbol="TEST", initial_capital=100_000).run(
            df, SmaCrossover(20, 50)
        )
        assert result.symbol == "TEST"
        assert isinstance(result.strategy_name, str)
        assert len(result.strategy_name) > 0
