"""Data Fetcher — Priority 1.

Fetches OHLCV and quote data from multiple providers.
Currently supports: yfinance (default), Angel One SmartAPI.

TODO (Phase 4 - Priority 1):
- Implement yfinance fetch
- Implement Angel One historical data fetch
- Add retry logic and error handling
- Add caching layer
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.base import BaseDataProvider
from core.logger import logger


class YFinanceProvider(BaseDataProvider):
    """Data provider using yfinance for historical OHLCV."""

    def initialize(self) -> bool:
        logger.info("YFinanceProvider initialized")
        return True

    def health_check(self) -> dict[str, Any]:
        return {"status": "ok", "provider": "yfinance"}

    def fetch_ohlcv(
        self, symbol: str, interval: str, from_date: str, to_date: str
    ) -> pd.DataFrame:
        """Fetch OHLCV data. TODO: implement in Phase 4 Priority 1."""
        logger.debug(f"fetch_ohlcv called: {symbol} {interval} {from_date} → {to_date}")
        raise NotImplementedError("TODO: Phase 4 Priority 1 — implement yfinance fetch")

    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch live quote. TODO: implement in Phase 4 Priority 1."""
        logger.debug(f"fetch_quote called: {symbol}")
        raise NotImplementedError("TODO: Phase 4 Priority 1 — implement live quote fetch")


class AngelOneProvider(BaseDataProvider):
    """Data provider using Angel One SmartAPI."""

    def initialize(self) -> bool:
        logger.info("AngelOneProvider initialized (not yet connected)")
        return False  # Will return True once API credentials are configured

    def health_check(self) -> dict[str, Any]:
        return {"status": "not_configured", "provider": "angel_one"}

    def fetch_ohlcv(
        self, symbol: str, interval: str, from_date: str, to_date: str
    ) -> pd.DataFrame:
        """TODO: Phase 4 Priority 1 — implement Angel One historical data."""
        raise NotImplementedError("TODO: Phase 4 Priority 1 — Angel One OHLCV")

    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        """TODO: Phase 4 Priority 1 — implement Angel One live quote."""
        raise NotImplementedError("TODO: Phase 4 Priority 1 — Angel One live quote")
