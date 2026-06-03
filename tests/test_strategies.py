"""Tests for strategy signal generators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.sma_crossover import SmaCrossover
from strategies.ema_crossover import EmaCrossover
from strategies.rsi_mean_reversion import RsiMeanReversion
from strategies.macd_signal import MacdSignal


def make_df(n: int = 200) -> pd.DataFrame:
    np.random.seed(42)
    close = pd.Series(np.cumsum(np.random.randn(n)) + 1000)
    df = pd.DataFrame({
        "Open": close * 0.99,
        "High": close * 1.01,
        "Low": close * 0.98,
        "Close": close,
        "Volume": np.random.randint(100000, 1000000, n).astype(float),
    })
    return df


class TestSmaCrossover:
    def test_returns_series(self):
        df = make_df()
        sig = SmaCrossover(20, 50).generate_signals(df)
        assert isinstance(sig, pd.Series)
        assert len(sig) == len(df)

    def test_values_are_1_or_minus1(self):
        df = make_df()
        sig = SmaCrossover(20, 50).generate_signals(df)
        assert set(sig.dropna().unique()).issubset({1, -1})


class TestEmaCrossover:
    def test_returns_series(self):
        df = make_df()
        sig = EmaCrossover(12, 26).generate_signals(df)
        assert isinstance(sig, pd.Series)


class TestRsiMeanReversion:
    def test_values_in_range(self):
        df = make_df()
        sig = RsiMeanReversion(14, 30, 70).generate_signals(df)
        assert set(sig.dropna().unique()).issubset({-1, 0, 1})


class TestMacdSignal:
    def test_returns_series(self):
        df = make_df()
        sig = MacdSignal(12, 26, 9).generate_signals(df)
        assert isinstance(sig, pd.Series)
        assert len(sig) == len(df)
