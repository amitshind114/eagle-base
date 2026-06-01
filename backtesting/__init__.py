"""Eagle-Base Backtesting Module — Priority 3.

Event-driven backtesting engine.
Runs any BaseStrategy over historical OHLCV data and produces metrics.
"""

from backtesting.engine import BacktestEngine
from backtesting.runner import BacktestRunner
from backtesting.result import BacktestResult
from backtesting.metrics import MetricsCalculator

__all__ = ["BacktestEngine", "BacktestRunner", "BacktestResult", "MetricsCalculator"]
