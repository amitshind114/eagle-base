"""Multi-broker abstraction layer for eagle-base.

Supported brokers (set BROKER env var):
  angelone | zerodha | upstox | fyers | iifl
"""

from brokers.registry import BrokerRegistry
from brokers.base import BrokerBase

__all__ = ["BrokerRegistry", "BrokerBase"]
