"""Yahoo Finance provider — Phase 3.

Wraps the existing DataFetcher (which already handles all NSE symbol
normalization, period capping, and weekend fallback).

This provider adds:
  - DataProvider interface compliance
  - datetime-range based fetching (from_dt / to_dt)
  - 3× retry with exponential backoff
  - Bulk download via yf.download() for multi-stock runs

NOTE: DataFetcher is NOT replaced — it is wrapped.
      All existing callers of DataFetcher continue to work unchanged.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import List

import pandas as pd
import yfinance as yf

from core.exceptions import DataFetchError
from core.logger import get_logger
from data.fetcher import DataFetcher
from instruments.symbol_resolver import SymbolResolver

from .base import DataProvider

log = get_logger("data.providers.yahoo")

_SUPPORTED_INTERVALS = [
    "1m", "2m", "3m", "5m", "15m", "30m",
    "60m", "1h", "90m",
    "1d", "5d", "1wk", "1mo", "3mo",
]


class YahooProvider(DataProvider):
    """Fetch data from Yahoo Finance via yfinance.

    Uses DataFetcher internally — no duplication of symbol resolution
    or period-capping logic.
    """

    def __init__(self, retries: int = 3, retry_delay: float = 1.5) -> None:
        self._fetcher = DataFetcher()
        self._resolver = SymbolResolver()
        self._retries = retries
        self._retry_delay = retry_delay

    # ── DataProvider interface ─────────────────────────────────────────────

    def name(self) -> str:
        return "Yahoo Finance"

    def is_available(self) -> bool:
        """Ping yfinance — try a tiny fetch for a known symbol."""
        try:
            ticker = yf.Ticker("^NSEI")
            info = ticker.fast_info
            return bool(info)
        except Exception:
            return False

    def supported_intervals(self) -> List[str]:
        return _SUPPORTED_INTERVALS

    def fetch(
        self,
        symbol: str,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch OHLCV using date range (from_dt → to_dt).

        Falls back to period-based fetch if date-range download returns empty.
        """
        self._validate_interval(interval)
        yf_sym = self._resolver.to_yf(symbol)
        if not yf_sym:
            raise DataFetchError(f"Cannot resolve symbol '{symbol}' to a YF ticker.")

        last_exc: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                log.info(
                    f"[Yahoo] {symbol} → {yf_sym} | {interval} | "
                    f"{from_dt.date()} → {to_dt.date()} (attempt {attempt})"
                )
                df = yf.Ticker(yf_sym).history(
                    start=from_dt.strftime("%Y-%m-%d"),
                    end=to_dt.strftime("%Y-%m-%d"),
                    interval=interval,
                    auto_adjust=True,
                    back_adjust=False,
                    prepost=False,
                )
                if df is not None and not df.empty:
                    return self._clean(df)
                # Empty result on first attempt — try period-based fallback
                if attempt == 1:
                    log.warning(f"[Yahoo] Empty range result for {yf_sym}, trying period fallback")
                    df = self._fetcher.fetch(symbol, period="1y", interval=interval)
                    return self._clean(df)
            except Exception as exc:
                last_exc = exc
                log.warning(f"[Yahoo] Attempt {attempt} failed for {yf_sym}: {exc}")
                if attempt < self._retries:
                    time.sleep(self._retry_delay * attempt)

        raise DataFetchError(
            f"Yahoo fetch failed for '{symbol}' after {self._retries} attempts: {last_exc}"
        )

    def fetch_latest_price(self, symbol: str) -> float:
        """Return latest price. Uses DataFetcher which handles weekends."""
        return self._fetcher.fetch_latest_price(symbol)

    def fetch_batch(
        self,
        symbols: List[str],
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Bulk download — much faster than sequential fetch() calls."""
        yf_map: dict[str, str] = {}
        for sym in symbols:
            yf_sym = self._resolver.to_yf(sym)
            if yf_sym:
                yf_map[sym] = yf_sym

        if not yf_map:
            return {}

        log.info(f"[Yahoo] Bulk download: {len(yf_map)} symbols ({interval})")
        try:
            raw = yf.download(
                list(yf_map.values()),
                start=from_dt.strftime("%Y-%m-%d"),
                end=to_dt.strftime("%Y-%m-%d"),
                interval=interval,
                auto_adjust=True,
                group_by="ticker",
                progress=False,
                threads=True,
            )
        except Exception as exc:
            log.error(f"[Yahoo] Bulk download failed: {exc}")
            return {}

        results: dict[str, pd.DataFrame] = {}
        yf_syms = list(yf_map.values())
        for orig_sym, yf_sym in yf_map.items():
            try:
                df = raw[yf_sym] if len(yf_syms) > 1 else raw
                df = self._clean(df)
                if not df.empty:
                    results[orig_sym] = df
            except Exception as exc:
                log.warning(f"[Yahoo] Bulk parse failed for {orig_sym}: {exc}")

        log.info(f"[Yahoo] Bulk done: {len(results)}/{len(symbols)} succeeded")
        return results
