"""Data Manager — Priority 1.

High-level interface combining fetcher + cache.
All other modules should use DataManager, not fetcher directly.

Usage:
    manager = DataManager()
    df = manager.get_ohlcv("RELIANCE.NS", "1d", "2024-01-01", "2024-12-31")
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.logger import logger
from data.cache import DataCache
from data.fetcher import YFinanceProvider


class DataManager:
    """Combines data fetching and caching into a single interface."""

    def __init__(self, provider=None, use_cache: bool = True):
        self.provider = provider or YFinanceProvider()
        self.cache = DataCache() if use_cache else None
        self.use_cache = use_cache

    def get_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        from_date: str = "",
        to_date: str = "",
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Get OHLCV data — checks cache first, fetches if not cached.

        Args:
            symbol:        Ticker e.g. 'RELIANCE.NS', 'NIFTY50=F'
            interval:      '1d', '1h', '15m', '5m'
            from_date:     'YYYY-MM-DD'
            to_date:       'YYYY-MM-DD'
            force_refresh: Skip cache and re-fetch from provider
        """
        if self.use_cache and not force_refresh:
            cached = self.cache.read(symbol, interval, from_date, to_date)
            if cached is not None:
                return cached

        df = self.provider.fetch_ohlcv(symbol, interval, from_date, to_date)

        if self.use_cache and not df.empty:
            self.cache.write(df, symbol, interval, from_date, to_date)

        return df

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """Get latest live quote for a symbol."""
        return self.provider.fetch_quote(symbol)

    def health_check(self) -> dict[str, Any]:
        """Check health of provider and cache."""
        return {
            "provider": self.provider.health_check(),
            "cache_files": len(self.cache.list_cached()) if self.cache else 0,
        }
