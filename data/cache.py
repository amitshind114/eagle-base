"""Data Cache — Priority 1.

Local Parquet-based cache for OHLCV data.
Avoids repeated API calls for the same symbol + interval + date range.

Cache location: data/cache/<symbol>_<interval>_<from>_<to>.parquet

Usage:
    cache = DataCache()
    df = cache.read("RELIANCE.NS", "1d", "2024-01-01", "2024-12-31")
    if df is None:
        df = provider.fetch_ohlcv(...)
        cache.write(df, "RELIANCE.NS", "1d", "2024-01-01", "2024-12-31")
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from core.logger import logger

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


class DataCache:
    """File-based OHLCV cache using Parquet format."""

    def _key(self, symbol: str, interval: str, from_date: str, to_date: str) -> Path:
        safe = symbol.replace(".", "_").replace("/", "_")
        filename = f"{safe}_{interval}_{from_date}_{to_date}.parquet"
        return CACHE_DIR / filename

    def read(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> Optional[pd.DataFrame]:
        """Read cached OHLCV data. Returns None if not cached."""
        path = self._key(symbol, interval, from_date, to_date)
        if path.exists():
            logger.debug(f"[cache] HIT — {path.name}")
            return pd.read_parquet(path)
        logger.debug(f"[cache] MISS — {path.name}")
        return None

    def write(
        self,
        df: pd.DataFrame,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> None:
        """Write OHLCV DataFrame to cache as Parquet."""
        if df.empty:
            logger.warning(f"[cache] Skipping write — empty DataFrame for {symbol}")
            return
        path = self._key(symbol, interval, from_date, to_date)
        df.to_parquet(path)
        logger.info(f"[cache] Saved — {path.name} ({len(df)} rows)")

    def invalidate(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> bool:
        """Delete a specific cache entry. Returns True if deleted."""
        path = self._key(symbol, interval, from_date, to_date)
        if path.exists():
            path.unlink()
            logger.info(f"[cache] Invalidated — {path.name}")
            return True
        return False

    def clear_all(self) -> int:
        """Delete ALL cache files. Returns count of deleted files."""
        files = list(CACHE_DIR.glob("*.parquet"))
        for f in files:
            f.unlink()
        logger.warning(f"[cache] Cleared {len(files)} cache files")
        return len(files)

    def list_cached(self) -> list[str]:
        """List all cached file names."""
        return [f.name for f in CACHE_DIR.glob("*.parquet")]
