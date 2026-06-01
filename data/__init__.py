"""Eagle-Base Data Module — Priority 1.

Handles all market data fetching, caching, and feeds.
Providers: yfinance (default), Angel One SmartAPI.
"""

from data.fetcher import YFinanceProvider, AngelOneProvider
from data.cache import DataCache

__all__ = ["YFinanceProvider", "AngelOneProvider", "DataCache"]
