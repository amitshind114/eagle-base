"""Market data fetcher — wraps yfinance with caching and error handling."""

from __future__ import annotations

from functools import lru_cache

import pandas as pd
import yfinance as yf

from core.exceptions import DataFetchError, InsufficientDataError
from core.logger import get_logger

log = get_logger("data.fetcher")


class DataFetcher:
    """Fetch OHLCV data from yfinance with validation."""

    def fetch(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
        min_bars: int = 30,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data.

        Args:
            symbol: Yahoo Finance ticker (e.g. 'RELIANCE.NS').
            period: Data period ('1d','5d','1mo','3mo','6mo','1y','2y','5y').
            interval: Bar interval ('1m','5m','15m','1h','1d','1wk','1mo').
            min_bars: Minimum bars required; raises if fewer returned.

        Returns:
            DataFrame with columns [Open, High, Low, Close, Volume].

        Raises:
            DataFetchError: On network or API failure.
            InsufficientDataError: When fewer bars than min_bars returned.
        """
        log.info(f"Fetching {symbol} | period={period} interval={interval}")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
        except Exception as exc:
            raise DataFetchError(f"Failed to fetch {symbol}: {exc}") from exc

        if df.empty:
            raise DataFetchError(f"No data returned for {symbol}")

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index)
        df = df.round(2)

        if len(df) < min_bars:
            raise InsufficientDataError(
                f"{symbol} returned only {len(df)} bars (min={min_bars})"
            )

        log.info(f"Fetched {len(df)} bars for {symbol}")
        return df

    def fetch_latest_price(self, symbol: str) -> float:
        """Return the latest closing price for a symbol."""
        try:
            df = yf.Ticker(symbol).history(period="1d")
            if df.empty:
                raise DataFetchError(f"No price data for {symbol}")
            return float(df["Close"].iloc[-1])
        except Exception as exc:
            raise DataFetchError(f"Price fetch failed for {symbol}: {exc}") from exc

    @lru_cache(maxsize=64)
    def get_info(self, symbol: str) -> dict:
        """Return yfinance .info dict (cached)."""
        try:
            return yf.Ticker(symbol).info or {}
        except Exception:
            return {}
