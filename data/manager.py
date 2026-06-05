"""Data Manager — Phase 2 (Phase 3 ready).

Single entry point for all data requests in the system.
Strategies, backtesting, UI — all use DataManager, never DataFetcher directly.

Layer order:
  1. In-memory cache (DataCache)       → fastest, TTL-aware
  2. Parquet disk cache (ParquetStorage) → fast, survives restarts
  3. yfinance via DataFetcher          → network, always fresh

Every dataset is:
  a. Validated (DataValidator) before being returned
  b. Cached in memory and on disk after fetch
  c. Auto-resolved via SymbolResolver (any input → yfinance ticker)

Usage:
    from data.manager import DataManager
    dm = DataManager()
    df    = dm.get("RELIANCE", period="1y", interval="1d")
    df5m  = dm.get("TCS", period="5d", interval="5m")
    price = dm.price("NIFTY")
    info  = dm.info("HDFCBANK")
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from core.logger import get_logger
from core.exceptions import DataFetchError, InsufficientDataError
from .fetcher import DataFetcher
from .validator import DataValidator
from .cache import DataCache
from .storage import ParquetStorage

log = get_logger("data.manager")

# Module-level singletons — shared across all DataManager instances
_fetcher   = DataFetcher()
_validator = DataValidator()
_mem_cache = DataCache()
_disk_cache = ParquetStorage()


class DataManager:
    """
    Single source of truth for all OHLCV data in the system.
    Strategies and UI should ONLY use this, not DataFetcher directly.
    """

    def get(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
        min_bars: int = 5,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Get validated OHLCV data for any symbol.

        Flow:
          memory cache → disk cache → yfinance fetch → validate → cache

        Args:
            symbol       : Any NSE symbol, index, or yfinance ticker.
            period       : "1d","5d","1mo","3mo","6mo","1y","2y","5y","max"
            interval     : "1m","3m","5m","15m","30m","1h","1d","1wk","1mo"
            min_bars     : Minimum bars required before returning data.
            force_refresh: Skip all caches and fetch fresh.

        Returns:
            Clean validated DataFrame [Open, High, Low, Close, Volume].

        Raises:
            DataFetchError       : Symbol not found or network error.
            InsufficientDataError: Not enough bars after cleaning.
        """
        sym_key = symbol.strip().upper()

        # ─ 1. Memory cache ─────────────────────────────────────────────────
        if not force_refresh:
            cached = _mem_cache.get(sym_key, interval)
            if cached is not None and len(cached) >= min_bars:
                log.debug(f"Memory cache hit: {sym_key}/{interval}")
                return cached

        # ─ 2. Disk cache (Parquet) ────────────────────────────────────────
        if not force_refresh and not _disk_cache.is_stale(sym_key, interval):
            disk_df = _disk_cache.read(sym_key, interval)
            if disk_df is not None and len(disk_df) >= min_bars:
                log.debug(f"Disk cache hit: {sym_key}/{interval}")
                _mem_cache.set(sym_key, interval, disk_df)
                return disk_df

        # ─ 3. Fetch from yfinance ───────────────────────────────────────
        log.info(f"Fetching fresh: {sym_key}/{interval} period={period}")
        raw_df = _fetcher.fetch(symbol, period=period, interval=interval, min_bars=2)

        # ─ 4. Validate ─────────────────────────────────────────────────────
        result = _validator.validate(raw_df, interval=interval, symbol=sym_key)
        if result.warnings:
            for w in result.warnings:
                log.warning(f"{sym_key}: {w}")
        if not result.passed:
            for issue in result.issues:
                log.error(f"{sym_key}: VALIDATION FAIL — {issue}")

        clean_df = result.clean_df

        if clean_df is None or len(clean_df) < min_bars:
            raise InsufficientDataError(
                f"'{symbol}' has {len(clean_df) if clean_df is not None else 0} clean bars "
                f"(need {min_bars}). Try a longer period."
            )

        # ─ 5. Store in caches ──────────────────────────────────────────────
        _mem_cache.set(sym_key, interval, clean_df)
        # Only persist daily+ to disk (intraday cache expires too fast to be useful)
        if interval in ("1d", "1wk", "1mo"):
            _disk_cache.write(sym_key, interval, clean_df)

        return clean_df

    def price(self, symbol: str) -> float:
        """
        Return latest price. Weekend/holiday safe. Never raises.
        Returns 0.0 on failure.
        """
        try:
            return _fetcher.fetch_latest_price(symbol)
        except Exception as exc:
            log.warning(f"price({symbol}) failed: {exc}")
            return 0.0

    def info(self, symbol: str) -> dict:
        """
        Return instrument metadata: name, sector, price, market cap.
        Never raises. Returns partial dict on failure.
        """
        return _fetcher.fetch_info(symbol)

    def batch_get(
        self,
        symbols: list[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch multiple symbols in one batch call.
        Returns dict {symbol: clean_df}. Skips failed symbols silently.
        """
        raw_map = _fetcher.fetch_batch(symbols, period=period, interval=interval)
        clean_map: dict[str, pd.DataFrame] = {}
        for sym, df in raw_map.items():
            result = _validator.validate(df, interval=interval, symbol=sym)
            if result.clean_df is not None and not result.clean_df.empty:
                clean_map[sym] = result.clean_df
                _mem_cache.set(sym.upper(), interval, result.clean_df)
        return clean_map

    def search(self, query: str) -> list[dict]:
        """Search available symbols by name or prefix."""
        return _fetcher.search_symbols(query)

    def cache_stats(self) -> dict:
        """Return memory and disk cache statistics."""
        return {
            "memory": _mem_cache.stats(),
            "disk": {
                "cached_entries": len(_disk_cache.list_cached()),
                "details": _disk_cache.cache_info(),
            },
        }

    def invalidate(self, symbol: str, interval: Optional[str] = None) -> None:
        """Force invalidate cache for a symbol."""
        _mem_cache.invalidate(symbol, interval)
        _disk_cache.invalidate(symbol, interval)
        log.info(f"Cache invalidated: {symbol}/{interval or 'all'}")
