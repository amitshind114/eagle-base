"""Data Manager — provider chain: Angel One → yfinance.

Single entry point for all data requests in the system.
Strategies, backtesting, UI — all use DataManager, never DataFetcher directly.

Provider priority (automatic, based on env vars):
  1. Angel One SmartAPI  — if ANGELONE_* env vars are set and login succeeds
  2. yfinance            — always available as fallback

Every data fetch logs which provider served the request:
  [DataManager] RELIANCE served by: Angel One SmartAPI
  [DataManager] TCS served by: yfinance (Angel One unavailable)

Cache layer (same as before — unchanged):
  1. In-memory cache (DataCache)         → fastest, TTL-aware
  2. Parquet disk cache (ParquetStorage) → fast, survives restarts
  3. Provider fetch                      → network

Usage (unchanged):
    from data.manager import DataManager
    dm = DataManager()
    df    = dm.get("RELIANCE", period="1y", interval="1d")
    price = dm.price("NIFTY")
    info  = dm.info("HDFCBANK")
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from core.logger import get_logger
from core.exceptions import DataFetchError, InsufficientDataError
from .fetcher import DataFetcher
from .validator import DataValidator
from .cache import DataCache
from .storage import ParquetStorage
from .providers.angel import AngelProvider

log = get_logger("data.manager")

# ── Period → timedelta map for provider fetch() ────────────────────────────
_PERIOD_TO_DAYS: dict[str, int] = {
    "1d":  1,   "2d":  2,   "5d":  5,   "1mo": 30,
    "3mo": 90,  "6mo": 180, "1y":  365,  "2y":  730,
    "5y":  1825, "max": 3650,
}

# Module-level singletons — shared across all DataManager instances
_fetcher    = DataFetcher()
_validator  = DataValidator()
_mem_cache  = DataCache()
_disk_cache = ParquetStorage()
_angel      = AngelProvider()   # initialised once; logs in lazily on first use


class DataManager:
    """
    Single source of truth for all OHLCV data.
    Provider chain: Angel One → yfinance.
    """

    # ── Public properties (test-required) ─────────────────────────────────

    @property
    def provider(self) -> DataFetcher:
        """Expose the underlying yfinance fetcher (backward compat)."""
        return _fetcher

    @property
    def cache(self) -> DataCache:
        return _mem_cache

    @property
    def angel(self) -> AngelProvider:
        """Direct access to Angel One provider (for scrip master search etc)."""
        return _angel

    def health_check(self) -> dict:
        """Return health of all data layer components."""
        try:
            fetcher_status = _fetcher.health_check() if hasattr(_fetcher, "health_check") else {"status": "ok"}
        except Exception as exc:
            fetcher_status = {"status": "error", "reason": str(exc)}

        angel_available = _angel.is_available()
        active_provider = "Angel One SmartAPI" if angel_available else "yfinance"

        ok          = fetcher_status.get("status") == "ok"
        cache_stats = _mem_cache.stats()

        return {
            "provider":       fetcher_status,
            "fetcher":        fetcher_status,
            "cache":          cache_stats,
            "cache_files":    cache_stats,
            "angel_online":   angel_available,
            "active_provider": active_provider,
            "status":         "ok" if ok else "degraded",
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
        Get validated OHLCV data.

        Provider chain:
          memory cache → disk cache → Angel One → yfinance → validate → cache

        Logs which provider served each request.
        """
        sym_key = symbol.strip().upper()

        # ─ 1. Memory cache ─────────────────────────────────────────────────
        if not force_refresh:
            cached = _mem_cache.get(sym_key, interval)
            if cached is not None and len(cached) >= min_bars:
                log.debug("[DataManager] %s/%s — memory cache hit", sym_key, interval)
                return cached

        # ─ 2. Disk cache ───────────────────────────────────────────────────
        if not force_refresh and not _disk_cache.is_stale(sym_key, interval):
            disk_df = _disk_cache.read(sym_key, interval)
            if disk_df is not None and len(disk_df) >= min_bars:
                log.debug("[DataManager] %s/%s — disk cache hit", sym_key, interval)
                _mem_cache.set(sym_key, interval, disk_df)
                return disk_df

        # ─ 3. Angel One (primary provider) ────────────────────────────────
        raw_df: Optional[pd.DataFrame] = None
        served_by: str = "yfinance"

        if _angel.is_available():
            days = _PERIOD_TO_DAYS.get(period, 365)
            to_dt   = datetime.now()
            from_dt = to_dt - timedelta(days=days)
            try:
                raw_df    = _angel.fetch(sym_key, from_dt, to_dt, interval)
                served_by = "Angel One SmartAPI"
                log.info(
                    "[DataManager] %s served by: Angel One SmartAPI (%d bars)",
                    sym_key, len(raw_df),
                )
            except Exception as exc:
                log.warning(
                    "[DataManager] Angel One fetch failed for %s: %s — "
                    "falling back to yfinance",
                    sym_key, exc,
                )
                raw_df = None
        else:
            log.debug(
                "[DataManager] Angel One not available — using yfinance for %s",
                sym_key,
            )

        # ─ 4. yfinance fallback ────────────────────────────────────────────
        if raw_df is None or raw_df.empty:
            served_by = "yfinance"
            log.info(
                "[DataManager] %s served by: yfinance%s",
                sym_key,
                " (Angel One unavailable)" if not _angel.is_available() else " (Angel One fallback)",
            )
            raw_df = _fetcher.fetch(
                symbol, period=period, interval=interval, min_bars=2
            )

        # ─ 5. Validate ─────────────────────────────────────────────────────
        result = _validator.validate(raw_df, interval=interval, symbol=sym_key)
        if result.warnings:
            for w in result.warnings:
                log.warning("%s: %s", sym_key, w)
        if not result.passed:
            for issue in result.issues:
                log.error("%s: VALIDATION FAIL — %s", sym_key, issue)

        clean_df = result.clean_df

        if clean_df is None or len(clean_df) < min_bars:
            raise InsufficientDataError(
                f"'{symbol}' has {len(clean_df) if clean_df is not None else 0} "
                f"clean bars (need {min_bars}). Try a longer period."
            )

        # ─ 6. Store in caches ──────────────────────────────────────────────
        _mem_cache.set(sym_key, interval, clean_df)
        if interval in ("1d", "1wk", "1mo"):
            _disk_cache.write(sym_key, interval, clean_df)

        return clean_df

    def price(self, symbol: str) -> float:
        """Return latest price. Angel One LTP first, yfinance fallback."""
        if _angel.is_available():
            try:
                p = _angel.fetch_latest_price(symbol)
                if p > 0:
                    log.debug("[DataManager] price(%s)=%.2f via Angel One", symbol, p)
                    return p
            except Exception:
                pass
        try:
            return _fetcher.fetch_latest_price(symbol)
        except Exception as exc:
            log.warning("price(%s) failed: %s", symbol, exc)
            return 0.0

    def info(self, symbol: str) -> dict:
        """Return instrument metadata."""
        return _fetcher.fetch_info(symbol)

    def batch_get(
        self,
        symbols: list[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols. Logs provider per symbol."""
        results: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                results[sym] = self.get(sym, period=period, interval=interval)
            except Exception as exc:
                log.warning("batch_get: skipping %s — %s", sym, exc)
        return results
