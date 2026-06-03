"""Tests for backtesting engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtesting.engine import BacktestEngine
from strategies.sma_crossover import SmaCrossover
from core.exceptions import InsufficientDataError


def make_df(n: int = 200) -> pd.DataFrame:
    np.random.seed(0)
    close = pd.Series(np.cumsum(np.random.randn(n)) + 1000)
    return pd.DataFrame({
        "Open": close * 0.99, "High": close * 1.01,
        "Low": close * 0.98, "Close": close,
        "Volume": np.random.randint(100000, 1000000, n).astype(float),
    })


class TestBacktestEngine:
    def test_returns_result(self):
        df = make_df()
        signals = SmaCrossover(20, 50).generate_signals(df)
        result = BacktestEngine().run(df, signals, capital=100_000)
        assert result.final_capital > 0
        assert -100 <= result.max_drawdown_pct <= 0
        assert 0 <= result.win_rate_pct <= 100

    def test_raises_on_short_data(self):
        df = make_df(5)
        signals = pd.Series([1] * 5)
        with pytest.raises(InsufficientDataError):
            BacktestEngine().run(df, signals)
