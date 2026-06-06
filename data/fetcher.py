"""Market data fetcher — Phase 04 hardened.

Fully resolves any user symbol → yfinance ticker → validated OHLCV.
Handles:
  - Any NSE symbol: RELIANCE, RELIANCE.NS, RELIANCE-EQ
  - Indices: NIFTY, BANKNIFTY, SENSEX
  - Intraday: 1m, 3m, 5m, 15m, 30m, 1h
  - Weekend / holiday: always returns last available session data
  - Bad data: empty result raises clear DataFetchError
  - 2d period on weekends: auto-upgraded to 5d (Yahoo returns empty on weekends)

Phase 04 changes:
  - _cap_period rewritten with TO_DAYS int-day dict (no more string order bugs)
  - 1h/60m cap fixed to 730d (was wrongly 60d)
  - tz_localize(None) removed — index stays tz-aware (Asia/Kolkata)
  - fetch_batch returns (dict, list[str]) — errors surfaced
  - fetch_latest_price has 10s timeout guard

Phase 04b fixes (June 2026):
  - TO_DAYS: added '2d' entry (was missing, caused silent KeyError fallthrough)
  - Weekend guard: period='2d' on Saturday/Sunday auto-upgrades to '5d'
    Yahoo Finance returns empty DataFrame for period='2d' on weekends because
    the last 2 calendar days contain no trading sessions.
  - fetch(): if DataFrame still empty after cap, retry once with 5d fallback
  - YFinanceProvider.fetch_ohlcv: same weekend guard applied

Usage:
    from data.fetcher import DataFetcher
    f = DataFetcher()
    df = f.fetch("RELIANCE", period="5d", interval="5m")
    price = f.fetch_latest_price("NIFTY")
    info  = f.fetch_info("TCS")
    results, errors = f.fetch_batch(["RELIANCE", "TCS", "INVALID"], period="1y")

    # Provider-style API (used by DataManager / tests)
    from data.fetcher import YFinanceProvider
    p = YFinanceProvider()
    df = p.fetch_ohlcv("AAPL", "1d", "2024-01-01", "2024-01-31")
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf

from core.exceptions import DataFetchError, InsufficientDataError
from core.logger import get_logger
from instruments.symbol_resolver import SymbolResolver

log = get_logger("data.fetcher")


# ── Period/interval limits ────────────────────────────────────────────────────────────────────────────────
#
# TO_DAYS: canonical day-count for every period/cap string.
# Used in _cap_period() to compare periods numerically, not by string position.
# This fixes the old bug where "60d" sorted AFTER "6mo" in an order[] list
# because it appeared later in the list — making 60 days look longer than 180.
#
TO_DAYS: dict[str, int] = {
    "1d":    1,
    "2d":    2,   # Phase 04b: was missing, caused KeyError fallthrough
    "5d":    5,
    "7d":    7,
    "1mo":   30,
    "2mo":   60,
    "3mo":   90,
    "60d":   60,
    "6mo":   180,
    "730d":  730,
    "1y":    365,
    "2y":    730,
    "3y":    1095,
    "5y":    1825,
    "10y":   3650,
    "max":   9999,
}

# Per-interval maximum period (yfinance hard limits).
# 1h/60m: yfinance actually returns up to 730 days of hourly data.
# 1m:     hard limit 7 days.
_INTERVAL_CAPS: dict[str, str] = {
    "1m":  "7d",
    "2m":  "60d",
    "3m":  "60d",
    "5m":  "60d",
    "15m": "60d",
    "30m": "60d",
    "60m": "730d",
    "1h":  "730d",
    "90m": "60d",
}

# Map user-friendly shorthand → yfinance interval string
_INTERVAL_ALIASES: dict[str, str] = {
    "1min": "1m", "1minute": "1m",
    "3min": "3m", "3minute": "3m",
    "5min": "5m", "5minute": "5m",
    "15min": "15m", "15minute": "15m",
    "30min": "30m", "30minute": "30m",
    "1hour": "1h", "60min": "1h",
    "daily": "1d", "day": "1d",
    "weekly": "1wk", "week": "1wk",
    "monthly": "1mo", "month": "1mo",
}

# Map user-friendly period shorthand → yfinance period string
_PERIOD_ALIASES: dict[str, str] = {
    "today": "1d",
    "1day": "1d",
    "1week": "5d",
    "1month": "1mo",
    "3months": "3mo",
    "6months": "6mo",
    "1year": "1y",
    "2years": "2y",
    "5years": "5y",
    "max": "max",
}

# Singleton resolver — shared across all DataFetcher instances
_resolver = SymbolResolver()


def _is_weekend() -> bool:
    """Return True if today (UTC) is Saturday or Sunday.

    Yahoo Finance returns an empty DataFrame for period='1d' or period='2d'
    on weekends because the last N calendar days contain no trading sessions.
    Callers should upgrade to '5d' so the last trading Friday is included.
    """
    return datetime.now(timezone.utc).weekday() >= 5  # 5=Sat, 6=Sun


def _weekend_safe_period(period: str) -> str:
    """Upgrade dangerously short periods on weekends.

    '1d' and '2d' on a Saturday/Sunday will return zero bars because the
    last 1-2 calendar days are non-trading.  Automatically promote to '5d'
    so at least Friday's session is returned.

    Any period of 5d or longer is safe and returned unchanged.
    """
    if not _is_weekend():
        return period
    short_periods = {"1d", "2d", "today", "1day"}
    if period in short_periods:
        log.warning(
            f"Weekend detected: period='{period}' would return 0 bars. "
            f"Auto-upgrading to '5d' to include last trading session (Friday)."
        )
        return "5d"
    return period


class DataFetcher:
    """Fetch OHLCV data. Resolves any symbol automatically."""

    def fetch(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
        min_bars: int = 2,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for any symbol.

        Args:
            symbol  : NSE symbol, YF ticker, or index name.
            period  : "1d","5d","1mo","3mo","6mo","1y","2y","5y","max"
            interval: "1m","3m","5m","15m","30m","1h","1d","1wk","1mo"
            min_bars: Minimum bars required (default 2).

        Returns:
            DataFrame with tz-aware DatetimeIndex (Asia/Kolkata),
            columns [Open, High, Low, Close, Volume].

        Raises:
            DataFetchError       : Symbol not found or network error.
            InsufficientDataError: Fewer than min_bars returned.
        """
        interval = _INTERVAL_ALIASES.get(interval.lower(), interval)
        period   = _PERIOD_ALIASES.get(period.lower(), period)
        period   = _weekend_safe_period(period)        # Phase 04b: weekend guard
        period   = self._cap_period(interval, period)

        yf_sym = _resolver.to_yf(symbol)
        if not yf_sym:
            raise DataFetchError(
                f"Cannot resolve symbol '{symbol}'. "
                f"Try the exact NSE symbol e.g. 'RELIANCE' or 'TCS'."
            )

        log.info(f"Fetching {symbol} → {yf_sym} | period={period} interval={interval}")

        try:
            df = yf.Ticker(yf_sym).history(
                period=period,
                interval=interval,
                auto_adjust=True,
                back_adjust=False,
                prepost=False,
            )
        except Exception as exc:
            raise DataFetchError(f"yfinance error for {yf_sym}: {exc}") from exc

        # Phase 04b: if still empty (e.g. holiday on a weekday), retry with 5d
        if (df is None or df.empty) and period not in ("5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"):
            log.warning(
                f"Empty result for {yf_sym} with period='{period}'. "
                f"Retrying with period='5d' (holiday / thin market fallback)."
            )
            try:
                df = yf.Ticker(yf_sym).history(
                    period="5d",
                    interval=interval,
                    auto_adjust=True,
                    back_adjust=False,
                    prepost=False,
                )
            except Exception as exc:
                raise DataFetchError(f"yfinance retry error for {yf_sym}: {exc}") from exc

        if df is None or df.empty:
            raise DataFetchError(
                f"No data returned for '{symbol}' ({yf_sym}). "
                f"Market may be closed or symbol delisted."
            )

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index)

        # Keep tz-aware. Convert to IST but DO NOT strip timezone.
        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata")
        else:
            df.index = df.index.tz_localize("Asia/Kolkata")

        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df = df.dropna(subset=["Close"])
        df = df.round(2)

        if len(df) < min_bars:
            raise InsufficientDataError(
                f"'{symbol}' returned {len(df)} bars (need {min_bars}). "
                f"Try a longer period or different interval."
            )

        log.info(f"Fetched {len(df)} bars for {yf_sym} ({interval})")
        return df

    def fetch_latest_price(self, symbol: str, timeout: float = 10.0) -> float:
        """Return latest available price. Weekend/holiday safe.

        Phase 04: wrapped with 10s timeout so a yfinance hang in a
        paper-trading minute-loop never freezes the entire thread.

        Raises:
            DataFetchError: on timeout or resolution failure.
        """
        def _get() -> float:
            return _resolver.get_price(symbol)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_get)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise DataFetchError(
                    f"fetch_latest_price('{symbol}') timed out after {timeout}s. "
                    f"Check network or yfinance rate limits."
                )

    def fetch_info(self, symbol: str) -> dict:
        """Return instrument metadata. Safe: returns partial dict on failure."""
        return _resolver.get_info(symbol)

    def fetch_batch(
        self,
        symbols: list[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> tuple[dict[str, pd.DataFrame], list[str]]:
        """Fetch multiple symbols in one yfinance call.

        Returns:
            (results, errors)
            results : dict mapping original symbol → cleaned DataFrame
            errors  : list of symbols that failed (unresolvable or parse error)
        """
        interval = _INTERVAL_ALIASES.get(interval.lower(), interval)
        period   = _PERIOD_ALIASES.get(period.lower(), period)
        period   = _weekend_safe_period(period)        # Phase 04b: weekend guard
        period   = self._cap_period(interval, period)

        yf_map: dict[str, str] = {}
        errors: list[str]      = []

        for sym in symbols:
            yf_sym = _resolver.to_yf(sym)
            if yf_sym:
                yf_map[sym] = yf_sym
            else:
                log.warning(f"[fetch_batch] Cannot resolve symbol '{sym}' — adding to errors")
                errors.append(sym)

        if not yf_map:
            log.warning(f"[fetch_batch] No valid symbols from {symbols}")
            return {}, errors

        yf_syms = list(yf_map.values())
        log.info(f"Batch fetching {len(yf_syms)} symbols ({interval})")

        try:
            raw = yf.download(
                yf_syms,
                period=period,
                interval=interval,
                auto_adjust=True,
                group_by="ticker",
                progress=False,
                threads=True,
            )
        except Exception as exc:
            log.error(f"Batch download failed: {exc}")
            errors.extend(yf_map.keys())
            return {}, errors

        results: dict[str, pd.DataFrame] = {}
        for orig_sym, yf_sym in yf_map.items():
            try:
                if len(yf_syms) == 1:
                    df = raw
                else:
                    df = raw[yf_sym]
                df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                df = df.dropna(subset=["Close"])
                df.index = pd.to_datetime(df.index)
                if df.index.tz is not None:
                    df.index = df.index.tz_convert("Asia/Kolkata")
                else:
                    df.index = df.index.tz_localize("Asia/Kolkata")
                df = df.sort_index().round(2)
                if not df.empty:
                    results[orig_sym] = df
                else:
                    log.warning(f"[fetch_batch] Empty DataFrame for {orig_sym}")
                    errors.append(orig_sym)
            except Exception as exc:
                log.warning(f"[fetch_batch] Parse failed for {orig_sym}: {exc}")
                errors.append(orig_sym)

        if errors:
            log.warning(f"[fetch_batch] {len(errors)} symbol(s) failed: {errors}")
        log.info(f"Batch fetch complete: {len(results)}/{len(symbols)} succeeded")
        return results, errors

    def search_symbols(self, query: str) -> list[dict]:
        """Search available symbols by name/prefix."""
        return _resolver.search_names(query)

    # ── Period cap ──────────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _cap_period(interval: str, period: str) -> str:
        """Enforce yfinance period limits per interval.

        Uses TO_DAYS integer comparison — no more string-order bugs.
        '2d' is correctly 2 days. '60d' is 60 days. '6mo' is 180 days.

        Phase 04 fix: 1h/60m cap changed from 60d to 730d.
        Phase 04b fix: '2d' added to TO_DAYS dict.
        """
        if interval not in _INTERVAL_CAPS:
            return period  # daily/weekly/monthly: no cap

        cap = _INTERVAL_CAPS[interval]
        cap_days    = TO_DAYS.get(cap, 9999)
        period_days = TO_DAYS.get(period, 9999)

        if period_days > cap_days:
            log.warning(
                f"Period '{period}' ({period_days}d) too large for interval '{interval}'. "
                f"Capping to '{cap}' ({cap_days}d)."
            )
            return cap
        return period


# ── YFinanceProvider — provider-style API used by DataManager & tests ────────

class YFinanceProvider:
    """Provider-style wrapper around yfinance for use by DataManager.

    Implements the interface expected by DataManager and test_data.py:
        - name: str
        - health_check() → dict
        - fetch_ohlcv(symbol, interval, from_date, to_date) → DataFrame
        - fetch_quote(symbol) → dict

    Note: fetch_ohlcv intentionally strips timezone for backward compatibility
    with DataManager and test_data.py which compare naive DatetimeIndex.
    DataFetcher.fetch() (above) keeps tz-aware for cross-symbol join safety.
    """

    name: str = "yfinance"

    def health_check(self) -> dict:
        """Return provider health status."""
        try:
            test = yf.Ticker("AAPL").fast_info
            _ = test.last_price
            return {"status": "ok", "provider": self.name}
        except Exception as exc:
            return {"status": "error", "provider": self.name, "error": str(exc)}

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV bars for any symbol.

        Phase 04b: weekend guard applied — period='1d'/'2d' auto-promoted
        to '5d' on Saturday/Sunday to avoid empty DataFrame.
        """
        interval = _INTERVAL_ALIASES.get(interval.lower(), interval)
        # Apply weekend guard only when using period (not explicit date range)
        if not (from_date and to_date):
            period = _weekend_safe_period(period or "1y")
        try:
            ticker = yf.Ticker(symbol)
            if from_date and to_date:
                df = ticker.history(
                    start=from_date,
                    end=to_date,
                    interval=interval,
                    auto_adjust=True,
                    prepost=False,
                )
            else:
                p = period or "1y"
                df = ticker.history(
                    period=p,
                    interval=interval,
                    auto_adjust=True,
                    prepost=False,
                )
        except Exception as exc:
            log.error(f"YFinanceProvider.fetch_ohlcv failed for {symbol}: {exc}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        df = df[cols].copy()
        df.index = pd.to_datetime(df.index)
        # YFinanceProvider strips tz for DataManager backward compat
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df = df.dropna(subset=["Close"])
        return df.round(2)

    def fetch_quote(self, symbol: str) -> dict:
        """
        Return latest quote for a symbol.

        Returns:
            dict with at minimum: symbol, price, currency.
            Returns {symbol, error} on failure.
        """
        try:
            info = yf.Ticker(symbol).fast_info
            return {
                "symbol": symbol,
                "price": getattr(info, "last_price", None),
                "prev_close": getattr(info, "previous_close", None),
                "currency": getattr(info, "currency", "INR"),
                "exchange": getattr(info, "exchange", ""),
            }
        except Exception as exc:
            log.warning(f"YFinanceProvider.fetch_quote failed for {symbol}: {exc}")
            return {"symbol": symbol, "error": str(exc)}
