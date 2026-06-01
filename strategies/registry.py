"""Strategy Registry — Priority 4.

Register and load strategies by name.
Allows dynamic strategy loading for UI and API.

Usage:
    registry = StrategyRegistry()
    registry.register(SMACrossoverStrategy)
    strategy = registry.get("sma_crossover", fast=10, slow=30)
"""

from __future__ import annotations

from typing import Type

from core.logger import logger
from strategies.base import BaseStrategy


class StrategyRegistry:
    """Registry for strategy classes — register once, instantiate anywhere."""

    def __init__(self):
        self._registry: dict[str, Type[BaseStrategy]] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Auto-register built-in strategies."""
        from strategies.sma_crossover import SMACrossoverStrategy
        from strategies.rsi_strategy import RSIStrategy
        self.register(SMACrossoverStrategy)
        self.register(RSIStrategy)
        logger.info(f"[registry] Loaded {len(self._registry)} strategies")

    def register(self, strategy_class: Type[BaseStrategy]) -> None:
        """Register a strategy class by its name attribute."""
        self._registry[strategy_class.name] = strategy_class
        logger.debug(f"[registry] Registered: {strategy_class.name}")

    def get(self, name: str, **params) -> BaseStrategy:
        """Instantiate a registered strategy by name.

        Args:
            name:   Strategy name e.g. 'sma_crossover', 'rsi_strategy'
            **params: Parameters passed to strategy __init__

        Returns:
            Instantiated strategy object

        Raises:
            KeyError if strategy name not found
        """
        if name not in self._registry:
            available = list(self._registry.keys())
            raise KeyError(f"Strategy '{name}' not found. Available: {available}")
        return self._registry[name](**params)

    def list_strategies(self) -> list[dict]:
        """List all registered strategies with metadata."""
        return [
            cls().__class__.__dict__ and cls().info()
            for cls in self._registry.values()
        ]

    def names(self) -> list[str]:
        """Return list of registered strategy names."""
        return list(self._registry.keys())

    def count(self) -> int:
        return len(self._registry)
