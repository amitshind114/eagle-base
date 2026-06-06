"""Abstract DataProvider — Phase 3.

Every concrete provider MUST implement this interface.
DataManager depends ONLY on this contract; it never imports
yfinance, Angel, or any other library directly.

Contract:
    fetch(symbol, from_dt, to_dt, interval) → DataFrame
    fetch_latest_price(symbol)              → float
    supported_intervals()                   → list[str]
    name()                                  → str
    is_available()                          → bool
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List

import pandas as pd


class DataProvider(ABC):
    """Abstract base class for all market data providers.

    Implementing a new provider:
        1. Subclass DataProvider
        2. Implement all @abstractmethod methods
        3. Register in DataManager via register_provider()

    The DataFrame returned by fetch() MUST have:
        - DatetimeIndex (tz-naive, Asia/Kolkata)
        - Columns: Open, High, Low, Close, Volume (float64)
        - No duplicate index values
        - No NaN in Close column
        - Sorted ascending
    """

    # ── Required interface ────────────────────────────────────────────────

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch OHLCV bars between from_dt and to_dt.

        Args:
            symbol  : NSE symbol e.g. 'RELIANCE', 'NIFTY'
            from_dt : Start datetime (inclusive)
            to_dt   : End datetime (inclusive)
            interval: Bar size — '1m','5m','15m','30m','1h','1d','1wk','1mo'

        Returns:
            Clean DataFrame (see class docstring for contract).

        Raises:
            DataFetchError        : Symbol unknown or network error.
            InsufficientDataError : Zero bars returned for valid symbol.
            NotImplementedError   : Interval not supported by this provider.
        """
        ...

    @abstractmethod
    def fetch_latest_price(self, symbol: str) -> float:
        """Return the most recent traded price.

        Weekend / holiday safe — returns last available close.
        """
        ...

    @abstractmethod
    def supported_intervals(self) -> List[str]:
        """Return the list of interval strings this provider supports.

        Example: ['1m', '5m', '15m', '1h', '1d', '1wk']
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Return human-readable provider name.

        Example: 'Yahoo Finance', 'Angel One', 'Local CSV'
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is currently usable.

        Check credentials, network, or file existence here.
        DataManager calls this before trying a provider.
        """
        ...

    # ── Optional override ─────────────────────────────────────────────────

    def fetch_batch(
        self,
        symbols: List[str],
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Fetch multiple symbols. Default: sequential loop.

        Override in providers that support bulk download (e.g. Yahoo)
        for a significant speed improvement.
        """
        results: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                df = self.fetch(sym, from_dt, to_dt, interval)
                if not df.empty:
                    results[sym] = df
            except Exception:
                pass
        return results

    # ── Helpers ────────────────────────────────────────────────────────────

    def _validate_interval(self, interval: str) -> None:
        """Raise NotImplementedError if interval is not supported."""
        if interval not in self.supported_intervals():
            raise NotImplementedError(
                f"Provider '{self.name()}' does not support interval '{interval}'. "
                f"Supported: {self.supported_intervals()}"
            )

    @staticmethod
    def _clean(df: pd.DataFrame) -> pd.DataFrame:
        """Enforce the DataFrame contract: standard columns, sorted, no dupes."""
        if df is None or df.empty:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df = df.dropna(subset=["Close"])
        df = df.astype({"Open": float, "High": float, "Low": float,
                        "Close": float, "Volume": float})
        return df.round(2)

    def __repr__(self) -> str:
        avail = "✓" if self.is_available() else "✗"
        return f"<{self.__class__.__name__} name='{self.name()}' available={avail}>"
