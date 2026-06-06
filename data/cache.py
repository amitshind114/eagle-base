"""In-memory LRU cache — Phase 2.

Thin layer sitting in front of ParquetStorage and the network fetcher.
Eliminates repeated yfinance calls for the same symbol+interval within a session.

TTL per interval:
  Intraday (1m-1h)  : 60 seconds  (refresh every minute max)
  Daily             : 6 hours
  Weekly / Monthly  : 24 hours

Usage:
    from data.cache import DataCache
    cache = DataCache()
    df = cache.get("RELIANCE.NS", "5m")
    if df is None:
        df = fetch_from_source()
        cache.set("RELIANCE.NS", "5m", df)
    cache.invalidate("RELIANCE.NS")
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from core.logger import get_logger

log = get_logger("data.cache")

# Module-level cache directory — monkeypatchable in tests
CACHE_DIR = Path("eagle_base/data/cache")

# TTL per interval
_TTL: dict[str, timedelta] = {
    "1m":  timedelta(seconds=60),
    "3m":  timedelta(seconds=60),
    "5m":  timedelta(seconds=60),
    "15m": timedelta(seconds=60),
    "30m": timedelta(seconds=120),
    "1h":  timedelta(seconds=300),
    "1d":  timedelta(hours=6),
    "1wk": timedelta(hours=24),
    "1mo": timedelta(hours=24),
}

_DEFAULT_TTL = timedelta(minutes=5)
_MAX_ENTRIES = 256


class DataCache:
    """In-memory LRU cache for OHLCV DataFrames with per-interval TTL."""

    def __init__(self) -> None:
        # key: (symbol, interval) → (df, expires_at)
        self._store: dict[tuple, tuple] = {}

    def get(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """Return cached DataFrame or None if missing/expired."""
        key = (symbol.upper(), interval)
        entry = self._store.get(key)
        if entry is None:
            return None
        df, expires_at = entry
        if datetime.now() > expires_at:
            del self._store[key]
            log.debug(f"Cache expired: {symbol}/{interval}")
            return None
        return df

    def set(self, symbol: str, interval: str, df: pd.DataFrame) -> None:
        """Store DataFrame in cache."""
        if df is None or df.empty:
            return
        if len(self._store) >= _MAX_ENTRIES:
            oldest_key = min(self._store, key=lambda k: self._store[k][1])
            del self._store[oldest_key]

        ttl = _TTL.get(interval, _DEFAULT_TTL)
        expires_at = datetime.now() + ttl
        key = (symbol.upper(), interval)
        self._store[key] = (df.copy(), expires_at)
        log.debug(f"Cached {len(df)} bars for {symbol}/{interval} (TTL={ttl})")

    def invalidate(self, symbol: str, interval: Optional[str] = None) -> None:
        """Remove cache entry/entries for a symbol."""
        sym = symbol.upper()
        if interval:
            self._store.pop((sym, interval), None)
        else:
            keys_to_del = [k for k in self._store if k[0] == sym]
            for k in keys_to_del:
                del self._store[k]

    def clear(self) -> None:
        """Clear entire cache."""
        self._store.clear()

    def stats(self) -> dict:
        """Return cache statistics."""
        now = datetime.now()
        live = sum(1 for _, (_, exp) in self._store.items() if now <= exp)
        return {
            "total_entries": len(self._store),
            "live_entries": live,
            "expired_entries": len(self._store) - live,
            "max_entries": _MAX_ENTRIES,
        }
