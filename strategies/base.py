"""Abstract base class for all strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    """All strategies must implement generate_signals."""

    name: str = "BaseStrategy"
    version: str = "1.0.0"
    description: str = ""

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Generate trading signals from OHLCV data.

        Args:
            df: OHLCV DataFrame.

        Returns:
            Series of 1 (long), -1 (short), 0 (flat).
        """
        ...

    def __repr__(self) -> str:
        return f"{self.name} v{self.version}"
