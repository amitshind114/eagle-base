"""Tests — Backtesting Module (Priority 3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtesting.engine import BacktestEngine
from backtesting.metrics import MetricsCalculator
from backtesting.result import BacktestResult, Trade
from backtesting.runner import BacktestRunner
from strategies.sma_crossover import SMACrossoverStrategy


def make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    close = np.maximum(close, 10)  # floor at 10
    df = pd.DataFrame({
        "Open":   close * (1 + rng.uniform(-0.005, 0.005, n)),
        "High":   close * (1 + rng.uniform(0, 0.01, n)),
        "Low":    close * (1 - rng.uniform(0, 0.01, n)),
        "Close":  close,
        "Volume": rng.integers(100_000, 1_000_000, n),
    }, index=pd.date_range("2023-01-01", periods=n, freq="B"))
    return df


class TestBacktestEngine:
    def test_run_returns_result(self):
        df = make_ohlcv(200)
        strategy = SMACrossoverStrategy(fast=10, slow=30)
        engine = BacktestEngine(symbol="TEST", initial_capital=100_000)
        result = engine.run(df, strategy)
        assert result is not None
        assert result.symbol == "TEST"
        assert result.initial_capital == 100_000

    def test_equity_curve_length(self):
        df = make_ohlcv(200)
        strategy = SMACrossoverStrategy(fast=10, slow=30)
        engine = BacktestEngine(symbol="TEST", initial_capital=100_000)
        result = engine.run(df, strategy)
        # equity curve = initial + 1 per bar
        assert len(result.equity_curve) == len(df) + 1

    def test_equity_curve_starts_at_capital(self):
        df = make_ohlcv(200)
        strategy = SMACrossoverStrategy(fast=10, slow=30)
        engine = BacktestEngine(symbol="TEST", initial_capital=50_000)
        result = engine.run(df, strategy)
        assert result.equity_curve[0] == 50_000

    def test_trades_are_valid(self):
        df = make_ohlcv(200)
        strategy = SMACrossoverStrategy(fast=10, slow=30)
        engine = BacktestEngine(symbol="TEST", initial_capital=100_000)
        result = engine.run(df, strategy)
        for trade in result.trades:
            assert trade.quantity > 0
            assert trade.entry_price > 0
            assert trade.exit_price > 0


class TestBacktestResult:
    def _make_result(self):
        result = BacktestResult(
            symbol="TEST", strategy_name="test", initial_capital=100_000,
            equity_curve=[100_000, 102_000, 101_000, 105_000],
        )
        result.trades = [
            Trade("TEST", "LONG", "2024-01-01", "2024-01-10",
                  100.0, 110.0, 10, pnl=100.0, pnl_pct=10.0),
            Trade("TEST", "LONG", "2024-02-01", "2024-02-10",
                  110.0, 105.0, 10, pnl=-50.0, pnl_pct=-4.5),
        ]
        return result

    def test_win_rate(self):
        result = self._make_result()
        assert result.win_rate == 50.0

    def test_total_trades(self):
        result = self._make_result()
        assert result.total_trades == 2

    def test_summary_string(self):
        result = self._make_result()
        summary = result.summary()
        assert "Backtest" in summary
        assert "Win Rate" in summary

    def test_to_trades_df(self):
        result = self._make_result()
        df = result.to_trades_df()
        assert len(df) == 2
        assert "pnl" in df.columns


class TestMetricsCalculator:
    def test_compute_returns_dict(self):
        result = BacktestResult(
            symbol="TEST", strategy_name="test", initial_capital=100_000,
            equity_curve=[100_000 + i * 100 for i in range(100)],
        )
        calc = MetricsCalculator()
        metrics = calc.compute(result)
        assert isinstance(metrics, dict)
        assert "sharpe_ratio" in metrics
        assert "max_drawdown_pct" in metrics
        assert "cagr_pct" in metrics

    def test_insufficient_data(self):
        result = BacktestResult(
            symbol="TEST", strategy_name="test", initial_capital=100_000,
            equity_curve=[100_000],
        )
        calc = MetricsCalculator()
        metrics = calc.compute(result)
        assert "error" in metrics
