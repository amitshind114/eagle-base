"""Eagle-Base StrategyContext Domain Model.

Provides a strategy with everything it needs to make a decision:
- Current and historical candles
- Computed indicators
- Open positions snapshot
- Portfolio state
- Metadata (timeframe, symbol, strategy name)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from domain.candle import Candle
from domain.position import Position
from domain.portfolio import Portfolio


class StrategyContext(BaseModel):
    """Immutable snapshot passed to strategy.generate_signals().

    Strategies must NOT modify state directly.
    They receive a StrategyContext and return Signal(s).
    """

    model_config = {"frozen": True}

    # --- Market Data ---
    symbol: str
    exchange: str
    timeframe: str = Field(default="1d")
    current_candle: Candle
    historical_candles: List[Candle] = Field(
        default_factory=list,
        description="Ordered oldest to newest, excludes current_candle",
    )

    # --- Indicators ---
    indicators: Dict[str, Any] = Field(
        default_factory=dict,
        description="Pre-computed indicator values keyed by name e.g. {'sma_20': 450.25}",
    )

    # --- Position & Portfolio State ---
    open_positions: Dict[str, Position] = Field(
        default_factory=dict,
        description="Currently open positions keyed by symbol",
    )
    portfolio: Optional[Portfolio] = Field(
        default=None,
        description="Full portfolio snapshot at this bar",
    )

    # --- Metadata ---
    strategy_name: str = Field(default="")
    bar_index: int = Field(default=0, ge=0, description="Sequential bar number since start")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # --- Convenience Properties ---

    @property
    def close(self) -> float:
        return self.current_candle.close

    @property
    def high(self) -> float:
        return self.current_candle.high

    @property
    def low(self) -> float:
        return self.current_candle.low

    @property
    def open(self) -> float:
        return self.current_candle.open

    @property
    def volume(self) -> float:
        return self.current_candle.volume

    @property
    def closes(self) -> List[float]:
        """All close prices: historical + current."""
        return [c.close for c in self.historical_candles] + [self.current_candle.close]

    @property
    def highs(self) -> List[float]:
        return [c.high for c in self.historical_candles] + [self.current_candle.high]

    @property
    def lows(self) -> List[float]:
        return [c.low for c in self.historical_candles] + [self.current_candle.low]

    @property
    def volumes(self) -> List[float]:
        return [c.volume for c in self.historical_candles] + [self.current_candle.volume]

    @property
    def has_position(self) -> bool:
        return self.symbol in self.open_positions

    @property
    def current_position(self) -> Optional[Position]:
        return self.open_positions.get(self.symbol)

    def indicator(self, name: str, default: Any = None) -> Any:
        """Safe indicator accessor."""
        return self.indicators.get(name, default)

    def __str__(self) -> str:
        return (
            f"StrategyContext[{self.strategy_name}] {self.symbol} "
            f"bar={self.bar_index} close={self.close:.2f} "
            f"candles={len(self.historical_candles)+1}"
        )
