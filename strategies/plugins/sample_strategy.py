"""Sample Strategy — Template for new strategies.

Copy this file and rename it to create a new strategy plugin.
All strategies must inherit from core.base.BaseStrategy.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.base import BaseStrategy


class SampleStrategy(BaseStrategy):
    """A simple moving average crossover strategy template."""

    name = "SampleStrategy"
    version = "1.0.0"
    description = "Simple MA crossover — template only, not production ready"

    def __init__(self, fast_period: int = 9, slow_period: int = 21):
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Generate buy/sell signals from OHLCV DataFrame.

        TODO: Implement actual signal logic.
        Returns DataFrame with 'signal' column: 1=buy, -1=sell, 0=hold.
        """
        raise NotImplementedError("TODO: Implement signal generation")

    def get_parameters(self) -> dict[str, Any]:
        return {
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
        }
