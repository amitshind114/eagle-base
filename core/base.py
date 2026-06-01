"""Eagle-Base Base Classes.

Abstract base classes that all major components inherit from.
Defines the standard interface contract across all modules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseModule(ABC):
    """Base class for all Eagle-Base modules."""

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the module. Return True if successful."""
        ...

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Return module health status as a dict."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


class BaseDataProvider(BaseModule):
    """Base class for all data providers."""

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, interval: str, from_date: str, to_date: str) -> Any:
        """Fetch OHLCV data for a symbol."""
        ...

    @abstractmethod
    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch live quote for a symbol."""
        ...


class BaseStrategy(ABC):
    """Base class for all trading strategies."""

    name: str = "BaseStrategy"
    version: str = "1.0.0"
    description: str = ""

    @abstractmethod
    def generate_signals(self, data: Any) -> Any:
        """Generate buy/sell signals from OHLCV data."""
        ...

    @abstractmethod
    def get_parameters(self) -> dict[str, Any]:
        """Return strategy parameters as a dict."""
        ...


class BaseExecutor(ABC):
    """Base class for paper and live executors."""

    @abstractmethod
    def place_order(self, symbol: str, side: str, qty: int, price: float) -> dict[str, Any]:
        """Place an order. Returns order response dict."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID. Return True if successful."""
        ...

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        """Return list of current open positions."""
        ...
