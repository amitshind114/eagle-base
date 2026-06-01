"""Data Cache — Priority 1.

Local caching layer for OHLCV data to avoid repeated API calls.
Stores data as Parquet files in data/cache/.

TODO (Phase 4 - Priority 1):
- Implement read_cache()
- Implement write_cache()
- Implement cache invalidation
"""

from __future__ import annotations

from pathlib import Path

from core.logger import logger

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


class DataCache:
    """Simple file-based cache for OHLCV data."""

    def read(self, key: str):
        """Read cached data by key. TODO: Phase 4 Priority 1."""
        logger.debug(f"Cache read: {key}")
        raise NotImplementedError("TODO: Phase 4 Priority 1")

    def write(self, key: str, data) -> None:
        """Write data to cache. TODO: Phase 4 Priority 1."""
        logger.debug(f"Cache write: {key}")
        raise NotImplementedError("TODO: Phase 4 Priority 1")

    def invalidate(self, key: str) -> None:
        """Remove a cached entry. TODO: Phase 4 Priority 1."""
        logger.debug(f"Cache invalidate: {key}")
        raise NotImplementedError("TODO: Phase 4 Priority 1")
