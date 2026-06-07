"""Angel One SmartAPI data provider — fully implemented.

Priority: Angel One (primary) → yfinance (fallback)

Activation (automatic — no config needed):
    Set these env vars in your CMD session before running:
        set ANGELONE_API_KEY=...
        set ANGELONE_CLIENT_ID=...
        set ANGELONE_PASSWORD=...
        set ANGELONE_TOTP_SECRET=...

    DataManager will automatically use Angel One as the primary provider.
    If env vars are missing or login fails, it silently falls back to yfinance.

Scrip Master:
    Fetched from Angel One's public JSON on first use or if >24h old.
    Saved to data/scrip_master.parquet for fast subsequent lookups.
    Covers: NSE EQ, NSE FO (F&O), BSE EQ, MCX (commodity),
            CDS (currency), ETF, indices — all segments.

Never hardcode credentials here. This file is safe to commit.
"""

from __future__ import annotations

import os
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

from core.logger import get_logger
from .base import DataProvider

log = get_logger("data.providers.angel")

# ── Constants ──────────────────────────────────────────────────────────────

_REQUIRED_ENV = [
    "ANGELONE_API_KEY",
    "ANGELONE_CLIENT_ID",
    "ANGELONE_PASSWORD",
    "ANGELONE_TOTP_SECRET",
]

_SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/"
    "OpenAPI_File/files/OpenAPIScripMaster.json"
)

# Parquet path relative to project root
_SCRIP_MASTER_PATH = Path("data") / "scrip_master.parquet"
_SCRIP_MASTER_MAX_AGE_H = 24   # refresh once per day

# Angel One interval string map
_INTERVAL_MAP: dict[str, str] = {
    "1m":  "ONE_MINUTE",
    "3m":  "THREE_MINUTE",
    "5m":  "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "1h":  "ONE_HOUR",
    "1d":  "ONE_DAY",
    "1wk": "ONE_DAY",   # weekly not native — fetch daily, resample upstream
}

_SUPPORTED_INTERVALS = list(_INTERVAL_MAP.keys())

# Default exchange per segment type
_EXCHANGE_MAP: dict[str, str] = {
    "EQ":      "NSE",
    "FO":      "NFO",
    "OPTIDX":  "NFO",
    "FUTIDX":  "NFO",
    "FUTSTK":  "NFO",
    "OPTSTK":  "NFO",
    "MCX":     "MCX",
    "CDS":     "CDS",
    "ETF":     "BSE",
    "INDEX":   "NSE",
    "BSE":     "BSE",
}


# ── Scrip Master ───────────────────────────────────────────────────────────

class ScripMaster:
    """
    Loads and caches Angel One's full instrument universe.

    On first call (or if >24h old) fetches the JSON from Angel One's
    public URL and saves to data/scrip_master.parquet.
    Subsequent calls load from disk — sub-second lookup.

    Covers all segments:
      NSE EQ, NSE FO (F&O), BSE EQ, MCX (commodity),
      CDS (currency / forex), ETF, Indices.
    """

    def __init__(self) -> None:
        self._df: Optional[pd.DataFrame] = None
        self._loaded_at: float = 0.0

    def load(self, force: bool = False) -> pd.DataFrame:
        """Return the full scrip master DataFrame. Refresh if stale."""
        age_h = (time.time() - self._loaded_at) / 3600
        if self._df is not None and age_h < _SCRIP_MASTER_MAX_AGE_H and not force:
            return self._df

        # Try disk cache first
        if not force and _SCRIP_MASTER_PATH.exists():
            mtime = _SCRIP_MASTER_PATH.stat().st_mtime
            disk_age_h = (time.time() - mtime) / 3600
            if disk_age_h < _SCRIP_MASTER_MAX_AGE_H:
                log.info("[ScripMaster] Loading from disk cache (age=%.1fh)", disk_age_h)
                self._df = pd.read_parquet(_SCRIP_MASTER_PATH)
                self._loaded_at = time.time()
                log.info("[ScripMaster] %d instruments loaded from disk", len(self._df))
                return self._df

        # Fetch from Angel One public URL
        log.info("[ScripMaster] Fetching full instrument universe from Angel One...")
        try:
            resp = requests.get(_SCRIP_MASTER_URL, timeout=30)
            resp.raise_for_status()
            raw: list[dict] = resp.json()
        except Exception as exc:
            log.error("[ScripMaster] Download failed: %s", exc)
            if _SCRIP_MASTER_PATH.exists():
                log.warning("[ScripMaster] Using stale disk cache as fallback")
                self._df = pd.read_parquet(_SCRIP_MASTER_PATH)
                return self._df
            raise RuntimeError(f"ScripMaster unavailable: {exc}") from exc

        df = pd.DataFrame(raw)

        # Normalise key columns
        rename = {
            "token":      "token",
            "symbol":     "symbol",
            "name":       "name",
            "expiry":     "expiry",
            "strike":     "strike",
            "lotsize":    "lot_size",
            "instrumenttype": "instrument_type",
            "exch_seg":   "exchange",
            "tick_size":  "tick_size",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

        # Keep only useful columns that exist
        keep = [c for c in [
            "token", "symbol", "name", "expiry", "strike",
            "lot_size", "instrument_type", "exchange", "tick_size"
        ] if c in df.columns]
        df = df[keep].copy()

        # Save to disk
        _SCRIP_MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(_SCRIP_MASTER_PATH, index=False)
        self._df = df
        self._loaded_at = time.time()

        # Summary log
        if "exchange" in df.columns:
            summary = df["exchange"].value_counts().to_dict()
            log.info("[ScripMaster] %d instruments saved. Segments: %s", len(df), summary)
        else:
            log.info("[ScripMaster] %d instruments saved to disk", len(df))

        return self._df

    def resolve_token(
        self,
        symbol: str,
        exchange: str = "NSE",
        instrument_type: str = "EQ",
    ) -> Optional[str]:
        """
        Resolve NSE/BSE symbol to Angel One token.

        Args:
            symbol          : e.g. 'RELIANCE', 'NIFTY', 'VEDANTA'
            exchange        : 'NSE', 'BSE', 'NFO', 'MCX', 'CDS'
            instrument_type : 'EQ', 'FUTIDX', 'OPTIDX', etc.

        Returns:
            Token string or None if not found.
        """
        df = self.load()
        sym_upper = symbol.strip().upper()

        # Try exact symbol + exchange match first
        if "exchange" in df.columns and "symbol" in df.columns:
            mask = (
                (df["symbol"].str.upper() == sym_upper) &
                (df["exchange"].str.upper() == exchange.upper())
            )
            matches = df[mask]

            # If multiple matches (F&O has many), filter by instrument_type
            if len(matches) > 1 and "instrument_type" in df.columns:
                typed = matches[
                    matches["instrument_type"].str.upper() == instrument_type.upper()
                ]
                if not typed.empty:
                    matches = typed

            if not matches.empty:
                token = str(matches.iloc[0]["token"])
                log.debug(
                    "[ScripMaster] %s/%s → token=%s", symbol, exchange, token
                )
                return token

        # Try name-based search as fallback
        if "name" in df.columns:
            name_mask = df["name"].str.upper().str.startswith(sym_upper)
            name_matches = df[name_mask]
            if not name_matches.empty:
                token = str(name_matches.iloc[0]["token"])
                log.debug(
                    "[ScripMaster] %s name-match → token=%s", symbol, token
                )
                return token

        log.warning("[ScripMaster] Token not found for %s/%s", symbol, exchange)
        return None

    def search(
        self,
        query: str,
        exchange: Optional[str] = None,
        instrument_type: Optional[str] = None,
        limit: int = 20,
    ) -> pd.DataFrame:
        """
        Search instruments by name or symbol prefix.

        Args:
            query           : Partial symbol or name e.g. 'RELIAN', 'NIFTY'
            exchange        : Optional filter e.g. 'NSE', 'MCX'
            instrument_type : Optional filter e.g. 'EQ', 'FUTIDX'
            limit           : Max results to return

        Returns:
            DataFrame of matching instruments with token, symbol, name,
            exchange, instrument_type, lot_size.
        """
        df = self.load()
        q = query.strip().upper()

        mask = pd.Series([True] * len(df), index=df.index)
        if "symbol" in df.columns:
            mask &= df["symbol"].str.upper().str.contains(q, na=False)
        if exchange and "exchange" in df.columns:
            mask &= df["exchange"].str.upper() == exchange.upper()
        if instrument_type and "instrument_type" in df.columns:
            mask &= df["instrument_type"].str.upper() == instrument_type.upper()

        return df[mask].head(limit).reset_index(drop=True)


# Module-level singleton — shared across all AngelProvider instances
_scrip_master = ScripMaster()


# ── AngelProvider ──────────────────────────────────────────────────────────

class AngelProvider(DataProvider):
    """
    Angel One SmartAPI data provider.

    Automatically active when ANGELONE_* env vars are set.
    Falls back gracefully — DataManager will use yfinance if unavailable.

    Data source priority in DataManager:
        1. Angel One (this provider)   ← real broker data
        2. yfinance                    ← fallback
    """

    def __init__(self) -> None:
        self._broker: Optional[object] = None
        self._connected: bool = False
        self._login_attempted: bool = False

    # ── DataProvider interface ─────────────────────────────────────────────

    def name(self) -> str:
        return "Angel One SmartAPI"

    def is_available(self) -> bool:
        """True only when ANGELONE_* env vars are set AND login succeeds."""
        missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
        if missing:
            log.debug("[AngelProvider] Not available — missing env: %s", missing)
            return False
        if self._connected:
            return True
        return self._try_login()

    def supported_intervals(self) -> List[str]:
        return _SUPPORTED_INTERVALS

    def fetch(
        self,
        symbol: str,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch OHLCV bars from Angel One SmartAPI.

        Args:
            symbol  : NSE symbol e.g. 'RELIANCE', 'VEDANTA', 'NIFTY'
            from_dt : Start datetime
            to_dt   : End datetime
            interval: '1m','5m','15m','30m','1h','1d'

        Returns:
            Clean DataFrame with DatetimeIndex and OHLCV columns.
        """
        self._validate_interval(interval)
        if not self._connected and not self._try_login():
            raise RuntimeError("[AngelProvider] Not connected to Angel One")

        angel_interval = _INTERVAL_MAP.get(interval, "ONE_DAY")

        # Resolve token from scrip master
        token = _scrip_master.resolve_token(symbol, exchange="NSE", instrument_type="EQ")
        if not token:
            raise ValueError(
                f"[AngelProvider] Cannot resolve token for '{symbol}'. "
                f"Check scrip master or try force_refresh."
            )

        from_str = from_dt.strftime("%Y-%m-%d %H:%M")
        to_str   = to_dt.strftime("%Y-%m-%d %H:%M")

        log.info(
            "[AngelProvider] Fetching %s | interval=%s | token=%s | %s → %s",
            symbol, interval, token, from_str, to_str,
        )

        try:
            raw = self._broker.get_candles(
                exchange="NSE",
                symbol_token=token,
                interval=angel_interval,
                from_date=from_str,
                to_date=to_str,
            )
        except Exception as exc:
            raise RuntimeError(
                f"[AngelProvider] get_candles failed for {symbol}: {exc}"
            ) from exc

        if not raw:
            raise RuntimeError(
                f"[AngelProvider] No data returned for '{symbol}' "
                f"(token={token}, interval={interval})"
            )

        df = pd.DataFrame(
            raw, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Close"])
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df = df.round(2)

        log.info(
            "[AngelProvider] ✓ %s — %d bars (%s to %s) via Angel One SmartAPI",
            symbol, len(df),
            df.index[0].date() if not df.empty else "?",
            df.index[-1].date() if not df.empty else "?",
        )
        return df

    def fetch_latest_price(self, symbol: str) -> float:
        """Return latest traded price via Angel One LTP."""
        if not self._connected and not self._try_login():
            return 0.0
        token = _scrip_master.resolve_token(symbol, exchange="NSE")
        if not token:
            return 0.0
        try:
            price = self._broker.get_ltp("NSE", symbol, token)
            log.debug("[AngelProvider] LTP %s = %.2f", symbol, price)
            return float(price)
        except Exception as exc:
            log.warning("[AngelProvider] LTP failed for %s: %s", symbol, exc)
            return 0.0

    # ── Internal ───────────────────────────────────────────────────────────

    def _try_login(self) -> bool:
        """Attempt Angel One login. Returns True on success."""
        if self._login_attempted and not self._connected:
            return False   # don't retry in same session if already failed
        self._login_attempted = True
        try:
            from brokers.adapters.angelone import AngelOneBroker
            broker = AngelOneBroker()
            ok = broker.login()
            if ok:
                self._broker = broker
                self._connected = True
                log.info("[AngelProvider] Connected to Angel One SmartAPI")
                # Pre-load scrip master in background on first connect
                try:
                    _scrip_master.load()
                except Exception as exc:
                    log.warning("[AngelProvider] Scrip master load warning: %s", exc)
                return True
            log.warning("[AngelProvider] Login returned False")
            return False
        except Exception as exc:
            log.warning("[AngelProvider] Login error: %s", exc)
            return False

    @property
    def scrip_master(self) -> ScripMaster:
        """Expose scrip master for external use (UI, search, token lookup)."""
        return _scrip_master
