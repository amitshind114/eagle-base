"""Abstract broker interface — every broker adapter must implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from brokers.models import BrokerOrder, BrokerPosition, BrokerProfile


class BrokerBase(ABC):
    """Broker-agnostic interface. Implement one adapter per broker."""

    name: str = "base"

    # ------------------------------------------------------------------ auth
    @abstractmethod
    def login(self) -> bool:
        """Authenticate and return True on success."""
        ...

    @abstractmethod
    def logout(self) -> bool:
        """Invalidate session."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the session is live."""
        ...

    # ------------------------------------------------------------------ profile
    @abstractmethod
    def get_profile(self) -> BrokerProfile:
        """Return authenticated user profile."""
        ...

    # ------------------------------------------------------------------ orders
    @abstractmethod
    def place_order(self, order: BrokerOrder) -> str:
        """Place order. Returns broker order_id."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        ...

    @abstractmethod
    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Return raw order status dict from broker."""
        ...

    @abstractmethod
    def get_orders(self) -> list[dict[str, Any]]:
        """Return today's order book."""
        ...

    # ------------------------------------------------------------------ positions
    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]:
        """Return open positions."""
        ...

    @abstractmethod
    def get_holdings(self) -> list[dict[str, Any]]:
        """Return demat holdings."""
        ...

    # ------------------------------------------------------------------ market data
    @abstractmethod
    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        """Return last traded price."""
        ...

    @abstractmethod
    def get_candles(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        """Return OHLCV candles as list of dicts."""
        ...

    # ------------------------------------------------------------------ funds
    @abstractmethod
    def get_funds(self) -> dict[str, Any]:
        """Return available margin/funds."""
        ...
