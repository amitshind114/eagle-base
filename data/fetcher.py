"""Market data fetcher — Phase 1 hardened.

Fully resolves any user symbol → yfinance ticker → validated OHLCV.
Handles:
  - Any NSE symbol: RELIANCE, RELIANCE.NS, RELIANCE-EQ
  - Indices: NIFTY, BANKNIFTY, SENSEX
  - Intraday: 1m, 3m, 5m, 15m, 30m, 1h
  - Weekend / holiday: always returns last available session data
  - Bad data: empty result raises clear DataFetchError

Usage:
    from data.fetcher import DataFetcher
    f = DataFetcher()
    df = f.fetch("RELIANCE", period="5d", interval="5m")
    price = f.fetch_latest_price("NIFTY")
    info  = f.fetch_info("TCS")

    # Provider-style API (used by DataManager / tests)
    from data.fetcher import YFinanceProvider
    p = YFinanceProvider()
    df = p.fetch_ohlcv("AAPL", "1d", "2024-01-01", "2024-01-31")
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from core.exceptions import DataFetchError, InsufficientDataError
from core.logger import get_logger
from instruments.symbol_resolver import SymbolResolver

log = get_logger("data.fetcher")

# ── Valid period/interval combinations (yfinance limits) ─────────────────
_VALID_COMBOS: dict[str, str] = {
    "1m":  "7d",
    "2m":  "60d",
    "3m":  "60d",
    "5m":  "60d",
    "15m": "60d",
    "30m": "60d",
    "60m": "730d",
    "1h":  "730d",
    "90m": "60d",
    "1d":  "max",
    "5d":  "max",
    "1wk": "max",
    "1mo": "max",
    "3mo": "max",
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
            DataFrame with DatetimeIndex, columns [Open,High,Low,Close,Volume].

        Raises:
            DataFetchError      : Symbol not found or network error.
            InsufficientDataError: Fewer than min_bars returned.
        """
        interval = _INTERVAL_ALIASES.get(interval.lower(), interval)
        period   = _PERIOD_ALIASES.get(period.lower(), period)
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

        if df is None or df.empty:
            raise DataFetchError(
                f"No data returned for '{symbol}' ({yf_sym}). "
                f"Market may be closed or symbol delisted."
            )

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
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

    def fetch_latest_price(self, symbol: str) -> float:
        """Return latest available price. Weekend/holiday safe."""
        return _resolver.get_price(symbol)

    def fetch_info(self, symbol: str) -> dict:
        """Return instrument metadata. Safe: returns partial dict on failure."""
        return _resolver.get_info(symbol)

    def fetch_batch(
        self,
        symbols: list[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Fetch multiple symbols in one yfinance call."""
        interval = _INTERVAL_ALIASES.get(interval.lower(), interval)
        period   = _PERIOD_ALIASES.get(period.lower(), period)
        period   = self._cap_period(interval, period)

        yf_map: dict[str, str] = {}
        for sym in symbols:
            yf_sym = _resolver.to_yf(sym)
            if yf_sym:
                yf_map[sym] = yf_sym

        if not yf_map:
            return {}

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
            return {}

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
                    df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
                df = df.sort_index().round(2)
                if not df.empty:
                    results[orig_sym] = df
            except Exception as exc:
                log.warning(f"Batch parse failed for {orig_sym}: {exc}")

        log.info(f"Batch fetch complete: {len(results)}/{len(symbols)} succeeded")
        return results

    def search_symbols(self, query: str) -> list[dict]:
        """Search available symbols by name/prefix."""
        return _resolver.search_names(query)

    @staticmethod
    def _cap_period(interval: str, period: str) -> str:
        """Enforce yfinance period limits per interval."""
        caps = {
            "1m":  "7d",
            "2m":  "60d",
            "3m":  "60d",
            "5m":  "60d",
            "15m": "60d",
            "30m": "60d",
            "60m": "60d",
            "1h":  "60d",
            "90m": "60d",
        }
        if interval in caps:
            order = ["1d","2d","5d","7d","1mo","3mo","6mo","60d","1y","2y","5y","max"]
            cap = caps[interval]
            try:
                if order.index(period) > order.index(cap):
                    log.warning(
                        f"Period '{period}' too large for interval '{interval}'. "
                        f"Capping to '{cap}'."
                    )
                    return cap
            except ValueError:
                return cap
        return period


# ── YFinanceProvider — provider-style API used by DataManager & tests ────

class YFinanceProvider:
    """Provider-style wrapper around yfinance for use by DataManager.

    Implements the interface expected by DataManager and test_data.py:
        - name: str
        - health_check() → dict
        - fetch_ohlcv(symbol, interval, from_date, to_date) → DataFrame
        - fetch_quote(symbol) → dict
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

        Args:
            symbol    : Ticker (e.g. "AAPL", "RELIANCE.NS").
            interval  : yfinance interval string ("1d", "1h", "5m", …).
            from_date : ISO date string "YYYY-MM-DD" (used with to_date).
            to_date   : ISO date string "YYYY-MM-DD".
            period    : yfinance period string ("1mo", "1y", …).
                        Use either period OR from_date/to_date, not both.

        Returns:
            DataFrame with DatetimeIndex, columns [Open, High, Low, Close, Volume].
            Returns empty DataFrame on failure.
        """
        interval = _INTERVAL_ALIASES.get(interval.lower(), interval)
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
