"""Dynamic broker factory and registry.

Usage:
    from brokers.registry import BrokerRegistry
    broker = BrokerRegistry.get("angelone")   # returns configured adapter
    broker = BrokerRegistry.get()             # reads BROKER env var
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brokers.base import BrokerBase

_ADAPTER_MAP: dict[str, str] = {
    "angelone": "brokers.adapters.angelone.AngelOneBroker",
    "zerodha":  "brokers.adapters.zerodha.ZerodhaBroker",
    "upstox":   "brokers.adapters.upstox.UpstoxBroker",
    "fyers":    "brokers.adapters.fyers.FyersBroker",
    "iifl":     "brokers.adapters.iifl.IIFLBroker",
}


class BrokerRegistry:
    """Factory that resolves and instantiates broker adapters by name."""

    @staticmethod
    def available() -> list[str]:
        return list(_ADAPTER_MAP.keys())

    @staticmethod
    def get(broker_name: str | None = None) -> "BrokerBase":
        """Return a broker adapter instance.

        Args:
            broker_name: One of the keys in _ADAPTER_MAP.
                         Falls back to BROKER environment variable.
                         Defaults to 'angelone' if neither is set.
        """
        name = (broker_name or os.getenv("BROKER", "angelone")).lower().strip()
        if name not in _ADAPTER_MAP:
            raise ValueError(
                f"Unknown broker '{name}'. "
                f"Available: {BrokerRegistry.available()}"
            )
        module_path, class_name = _ADAPTER_MAP[name].rsplit(".", 1)
        import importlib
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()
