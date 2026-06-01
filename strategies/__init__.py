"""Eagle-Base Strategies Module — Priority 4.

Strategy plugin system.
All strategies inherit from BaseStrategy and implement on_bar().
"""

from strategies.base import BaseStrategy, Signal
from strategies.registry import StrategyRegistry
from strategies.sma_crossover import SMACrossoverStrategy
from strategies.rsi_strategy import RSIStrategy

__all__ = [
    "BaseStrategy",
    "Signal",
    "StrategyRegistry",
    "SMACrossoverStrategy",
    "RSIStrategy",
]
