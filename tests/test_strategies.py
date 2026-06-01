"""Tests — Strategies Module (Priority 4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.base import BaseStrategy
from strategies.sma_crossover import SMACrossoverStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.registry import StrategyRegistry


def make_trending_df(n: int = 150) -> pd.DataFrame:
    """Trending up data — should trigger SMA golden cross."""
    close = np.linspace(100, 200, n)
    return pd.DataFrame({
        "Open": close * 0.999,
        "High": close * 1.005,
        "Low":  close * 0.995,
        "Close": close,
        "Volume": np.ones(n) * 100_000,
    }, index=pd.date_range("2023-01-01", periods=n, freq="B"))


def make_oscillating_df(n: int = 150) -> pd.DataFrame:
    """Oscillating data — should trigger RSI signals."""
    close = 100 + 20 * np.sin(np.linspace(0, 6 * np.pi, n))
    return pd.DataFrame({
        "Open": close * 0.999,
        "High": close * 1.005,
        "Low":  close * 0.995,
        "Close": close,
        "Volume": np.ones(n) * 100_000,
    }, index=pd.date_range("2023-01-01", periods=n, freq="B"))


class TestSMACrossoverStrategy:
    def test_init_valid(self):
        s = SMACrossoverStrategy(fast=10, slow=30)
        assert s.fast == 10
        assert s.slow == 30

    def test_init_invalid(self):
        with pytest.raises(ValueError):
            SMACrossoverStrategy(fast=50, slow=20)

    def test_hold_on_insufficient_data(self):
        s = SMACrossoverStrategy(fast=10, slow=30)
        df = make_trending_df(20)
        signal = s.on_bar(df)
        assert signal == "HOLD"

    def test_returns_valid_signal(self):
        s = SMACrossoverStrategy(fast=10, slow=30)
        df = make_trending_df(150)
        signals = set()
        for i in range(31, len(df)):
            sig = s.on_bar(df.iloc[:i])
            assert sig in ("BUY", "SELL", "HOLD")
            signals.add(sig)
        # Trending up data should produce BUY signal
        assert "BUY" in signals

    def test_reset_clears_state(self):
        s = SMACrossoverStrategy()
        s.set_state("test", 123)
        s.reset()
        assert s.get_state("test") is None

    def test_info(self):
        s = SMACrossoverStrategy(fast=20, slow=50)
        info = s.info()
        assert info["name"] == "sma_crossover"
        assert "fast" in info["params"]


class TestRSIStrategy:
    def test_init(self):
        s = RSIStrategy(period=14, oversold=30, overbought=70)
        assert s.period == 14

    def test_hold_on_insufficient_data(self):
        s = RSIStrategy(period=14)
        df = make_oscillating_df(10)
        assert s.on_bar(df) == "HOLD"

    def test_returns_valid_signal(self):
        s = RSIStrategy(period=14)
        df = make_oscillating_df(150)
        for i in range(16, len(df)):
            sig = s.on_bar(df.iloc[:i])
            assert sig in ("BUY", "SELL", "HOLD")

    def test_rsi_computed_correctly(self):
        s = RSIStrategy(period=14)
        df = make_oscillating_df(150)
        rsi = s._compute_rsi(df["Close"])
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()


class TestStrategyRegistry:
    def test_init_loads_defaults(self):
        registry = StrategyRegistry()
        assert registry.count() >= 2

    def test_get_sma(self):
        registry = StrategyRegistry()
        s = registry.get("sma_crossover", fast=10, slow=30)
        assert isinstance(s, SMACrossoverStrategy)

    def test_get_rsi(self):
        registry = StrategyRegistry()
        s = registry.get("rsi_strategy", period=14)
        assert isinstance(s, RSIStrategy)

    def test_get_unknown_raises(self):
        registry = StrategyRegistry()
        with pytest.raises(KeyError):
            registry.get("nonexistent_strategy")

    def test_names(self):
        registry = StrategyRegistry()
        assert "sma_crossover" in registry.names()
        assert "rsi_strategy" in registry.names()
