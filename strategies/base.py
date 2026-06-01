"""Base Strategy — Priority 4.

All strategies must inherit from BaseStrategy and implement on_bar().

Signals:
    'BUY'  — open long position
    'SELL' — close long position
    'HOLD' — do nothing

Usage:
    class MyStrategy(BaseStrategy):
        name = "my_strategy"

        def on_bar(self, df: pd.DataFrame) -> Signal:
            # df contains all bars up to and including current bar
            close = df["Close"].iloc[-1]
            return "BUY" if close > 100 else "HOLD"
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

import pandas as pd

# Signal type — BUY, SELL, or HOLD
Signal = Literal["BUY", "SELL", "HOLD"]


class BaseStrategy(ABC):
    """Abstract base class for all Eagle-Base strategies."""

    name: str = "base_strategy"
    description: str = ""
    version: str = "1.0.0"

    def __init__(self, **params):
        """Initialise strategy with optional parameters."""
        self.params = params
        self._state: dict = {}

    @abstractmethod
    def on_bar(self, df: pd.DataFrame) -> Signal:
        """Called on each new bar. Return BUY, SELL, or HOLD.

        Args:
            df: OHLCV DataFrame containing all bars up to current bar.
                Use df.iloc[-1] for current bar, df.iloc[-2] for previous.

        Returns:
            Signal: 'BUY', 'SELL', or 'HOLD'
        """
        ...

    def reset(self) -> None:
        """Reset internal state before a new backtest run."""
        self._state = {}

    def set_state(self, key: str, value) -> None:
        self._state[key] = value

    def get_state(self, key: str, default=None):
        return self._state.get(key, default)

    def info(self) -> dict:
        """Return strategy metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "params": self.params,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, params={self.params})"
