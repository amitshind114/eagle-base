"""Data Fetcher — Priority 1.

Fetches OHLCV and live quote data.
Providers: yfinance (free, no auth), Angel One SmartAPI (requires credentials).

Usage:
    from data.fetcher import YFinanceProvider
    provider = YFinanceProvider()
    df = provider.fetch_ohlcv("RELIANCE.NS", "1d", "2024-01-01", "2024-12-31")
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf

from core.logger import logger


class YFinanceProvider:
    """Fetches historical OHLCV data using yfinance (free, no API key needed)."""

    name = "yfinance"

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        from_date: str = "",
        to_date: str = "",
    ) -> pd.DataFrame:
        """Fetch OHLCV data for a symbol.

        Args:
            symbol:    Ticker symbol e.g. 'RELIANCE.NS', 'NIFTY50=F', 'AAPL'
            interval:  '1d', '1h', '15m', '5m', '1m'
            from_date: 'YYYY-MM-DD'
            to_date:   'YYYY-MM-DD'

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume
        """
        logger.info(f"[yfinance] Fetching {symbol} | {interval} | {from_date} → {to_date}")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                interval=interval,
                start=from_date if from_date else None,
                end=to_date if to_date else None,
            )
            if df.empty:
                logger.warning(f"[yfinance] No data returned for {symbol}")
                return pd.DataFrame()

            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.index = pd.to_datetime(df.index)
            df.index.name = "datetime"
            logger.info(f"[yfinance] Fetched {len(df)} rows for {symbol}")
            return df

        except Exception as e:
            logger.error(f"[yfinance] Error fetching {symbol}: {e}")
            return pd.DataFrame()

    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch latest quote for a symbol."""
        logger.info(f"[yfinance] Fetching quote: {symbol}")
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            return {
                "symbol": symbol,
                "price": getattr(info, "last_price", None),
                "open": getattr(info, "open", None),
                "high": getattr(info, "day_high", None),
                "low": getattr(info, "day_low", None),
                "volume": getattr(info, "last_volume", None),
                "provider": "yfinance",
            }
        except Exception as e:
            logger.error(f"[yfinance] Quote error for {symbol}: {e}")
            return {"symbol": symbol, "error": str(e)}

    def health_check(self) -> dict[str, Any]:
        """Check if yfinance is reachable."""
        try:
            yf.Ticker("AAPL").fast_info
            return {"status": "ok", "provider": "yfinance"}
        except Exception as e:
            return {"status": "error", "provider": "yfinance", "error": str(e)}


class AngelOneProvider:
    """Fetches data via Angel One SmartAPI.

    Requires environment variables:
        ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET

    Status: Skeleton ready — implement after credentials are configured.
    """

    name = "angel_one"

    def __init__(self):
        self._session = None
        self._connected = False

    def connect(self) -> bool:
        """Establish SmartAPI session. TODO: implement with credentials."""
        logger.warning("[AngelOne] Not yet connected — add credentials to .env")
        return False

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: str = "ONE_DAY",
        from_date: str = "",
        to_date: str = "",
    ) -> pd.DataFrame:
        """Fetch OHLCV from Angel One.

        Angel One intervals: ONE_MINUTE, THREE_MINUTE, FIVE_MINUTE,
                             TEN_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE,
                             ONE_HOUR, ONE_DAY
        """
        if not self._connected:
            logger.error("[AngelOne] Not connected. Call connect() first.")
            return pd.DataFrame()
        raise NotImplementedError("TODO: Implement Angel One OHLCV fetch")

    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch live quote from Angel One. TODO: implement."""
        if not self._connected:
            return {"symbol": symbol, "error": "Not connected"}
        raise NotImplementedError("TODO: Implement Angel One live quote")

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "not_configured" if not self._connected else "ok",
            "provider": "angel_one",
        }
