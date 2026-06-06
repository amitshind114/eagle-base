"""Data Manager — Phase 2 (Phase 3 ready).

Single entry point for all data requests in the system.
Strategies, backtesting, UI — all use DataManager, never DataFetcher directly.

Layer order:
  1. In-memory cache (DataCache)         → fastest, TTL-aware
  2. Parquet disk cache (ParquetStorage) → fast, survives restarts
  3. yfinance via DataFetcher            → network, always fresh

Every dataset is:
  a. Validated (DataValidator) before being returned
  b. Cached in memory and on disk after fetch

Usage:
    from data.manager import DataManager
    dm = DataManager()
    df    = dm.get("RELIANCE", period="1y", interval="1d")
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
_fetcher    = DataFetcher()
_validator  = DataValidator()
_mem_cache  = DataCache()
_disk_cache = ParquetStorage()


class DataManager:
    """
    Single source of truth for all OHLCV data in the system.
    Strategies and UI should ONLY use this, not DataFetcher directly.
    """

    # ── Public properties (test-required) ─────────────────────────────────

    @property
    def provider(self) -> DataFetcher:
        """Expose the underlying data fetcher as the primary provider."""
        return _fetcher

    @property
    def cache(self) -> DataCache:
        """Expose the in-memory cache."""
        return _mem_cache

    def health_check(self) -> dict:
        """Return health status of all data layer components."""
        try:
            fetcher_status = _fetcher.health_check() if hasattr(_fetcher, "health_check") else {"status": "ok"}
        except Exception as exc:
            fetcher_status = {"status": "error", "reason": str(exc)}

        ok = fetcher_status.get("status") == "ok"
        return {
            "provider": fetcher_status,      # tests check for 'provider' key
            "fetcher":  fetcher_status,      # keep backward-compat key too
            "cache":    _mem_cache.stats(),
            "status":   "ok" if ok else "degraded",
        }

    # ── Data access ───────────────────────────────────────────────────────

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

        # ─ 3. Fetch from yfinance ──────────────────────────────────────────
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
        """Return instrument metadata. Never raises."""
        return _fetcher.fetch_info(symbol)

    def batch_get(
        self,
        symbols: list[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols. Skips failures silently."""
        results: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                results[sym] = self.get(sym, period=period, interval=interval)
            except Exception as exc:
                log.warning(f"batch_get: skipping {sym} — {exc}")
        return results
