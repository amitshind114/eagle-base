"""Permanent Symbol Resolver — Phase 1 Fix.

This is the SINGLE source of truth for:
  user_input → valid yfinance ticker → OHLCV data

Strategy:
  1. Try nsepython (live NSE symbol list, no broker needed)
  2. Try jugaad-trader NSE equity list
  3. Try pandas_datareader NSE list
  4. Fallback: append .NS and validate with yfinance fast probe
  5. Last resort: search yfinance directly

This means:
  - F&O expiry changes → handled automatically
  - New listings → picked up on next refresh
  - Broker API not required until Phase 10 live trading
  - Strategies/data layer NEVER see broken symbols

Usage:
    from instruments.symbol_resolver import SymbolResolver
    r = SymbolResolver()
    yf_sym = r.to_yf("RELIANCE")     # → "RELIANCE.NS"
    yf_sym = r.to_yf("NIFTY")        # → "^NSEI"
    yf_sym = r.to_yf("RELIANCE.NS")  # → "RELIANCE.NS" (pass-through)
    info   = r.get_info("RELIANCE")   # → {name, sector, exchange, ...}
    price  = r.get_price("RELIANCE")  # → float
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from core.logger import get_logger

log = get_logger("instruments.symbol_resolver")

_CACHE_PATH = Path("eagle_base/data/symbol_cache.csv")
_STALE_HOURS = 24

# ── Static maps for indices (never change) ───────────────────────────────
_INDEX_MAP: dict[str, str] = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "BANK NIFTY": "^NSEBANK",
    "NIFTYBANK": "^NSEBANK",
    "SENSEX": "^BSESN",
    "BSE SENSEX": "^BSESN",
    "NIFTYMIDCAP100": "^NSEMDCP50",
    "NIFTYIT": "^CNXIT",
    "NIFTY IT": "^CNXIT",
    "NIFTYPHARMA": "^CNXPHARMA",
    "NIFTYAUTO": "^CNXAUTO",
    "NIFTYFMCG": "^CNXFMCG",
    "NIFTYINFRA": "^CNXINFRA",
    "NIFTYREALTY": "^CNXREALTY",
    "NIFTYENERGY": "^CNXENERGY",
    "NIFTYMETAL": "^CNXMETAL",
    "NIFTYMEDIA": "^CNXMEDIA",
}

# ── Known overrides (symbols that differ from simple .NS append) ─────────
_OVERRIDE_MAP: dict[str, str] = {
    "M&M": "M&M.NS",
    "L&T": "LT.NS",
    "LT": "LT.NS",
    "LTIM": "LTIM.NS",
    "BPCL": "BPCL.NS",
    "HINDPETRO": "HINDPETRO.NS",
    "HEROMOTOCO": "HEROMOTOCO.NS",
    "BAJAJ-AUTO": "BAJAJ-AUTO.NS",
    "BAJAJ AUTO": "BAJAJ-AUTO.NS",
    "NIFTY_50": "^NSEI",
    "NIFTYBANK_NSE": "^NSEBANK",
}


class SymbolResolver:
    """
    Converts ANY user input into a valid yfinance ticker.
    Self-healing: builds and caches a symbol list from NSE on first run.
    Never breaks on expiry changes or new listings.
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}   # input → yf_symbol
        self._master: dict[str, str] = {}  # NSE_SYMBOL → yf_symbol
        self._load_master()

    # ── Primary API ──────────────────────────────────────────────────────

    def to_yf(self, raw: str) -> str:
        """
        Convert any user input to a valid yfinance ticker.
        Returns empty string if resolution fails.
        """
        if not raw:
            return ""
        key = raw.strip().upper()

        # 1. Already in cache
        if key in self._cache:
            return self._cache[key]

        # 2. Already a valid yf ticker (has . suffix or ^ prefix)
        if key.startswith("^") or ".NS" in key or ".BO" in key:
            result = key if ".NS" in key or ".BO" in key else key
            self._cache[key] = result
            return result

        # 3. Index map (static, never changes)
        if key in _INDEX_MAP:
            self._cache[key] = _INDEX_MAP[key]
            return _INDEX_MAP[key]

        # 4. Override map
        if key in _OVERRIDE_MAP:
            self._cache[key] = _OVERRIDE_MAP[key]
            return _OVERRIDE_MAP[key]

        # 5. Strip known suffixes: -EQ, -FUT, -CE, -PE
        base = key.replace("-EQ", "").replace("-FUT", "").replace("-CE", "").replace("-PE", "")

        # 6. Master list lookup (NSE equity list)
        if base in self._master:
            self._cache[key] = self._master[base]
            return self._master[base]

        # 7. Fast probe: append .NS and check yfinance returns data
        candidate = f"{base}.NS"
        if self._probe_yf(candidate):
            self._master[base] = candidate
            self._cache[key] = candidate
            self._save_master()
            return candidate

        # 8. BSE fallback
        candidate_bse = f"{base}.BO"
        if self._probe_yf(candidate_bse):
            self._master[base] = candidate_bse
            self._cache[key] = candidate_bse
            self._save_master()
            return candidate_bse

        log.warning(f"Could not resolve symbol: {raw}")
        return ""

    def get_info(self, raw: str) -> dict:
        """
        Return instrument metadata: name, sector, exchange, currency, lotSize.
        Never raises — returns empty dict on failure.
        """
        yf_sym = self.to_yf(raw)
        if not yf_sym:
            return {}
        try:
            info = yf.Ticker(yf_sym).info or {}
            return {
                "symbol": raw.upper(),
                "yf_symbol": yf_sym,
                "name": info.get("longName") or info.get("shortName", raw),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "exchange": info.get("exchange", "NSE"),
                "currency": info.get("currency", "INR"),
                "market_cap": info.get("marketCap", 0),
                "lot_size": info.get("sharesOutstanding", 1),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice", 0),
            }
        except Exception as exc:
            log.warning(f"get_info failed for {raw}: {exc}")
            return {"symbol": raw, "yf_symbol": yf_sym}

    def get_price(self, raw: str) -> float:
        """
        Return latest price. 0.0 on failure.
        Weekend/holiday safe: uses last available close.
        """
        yf_sym = self.to_yf(raw)
        if not yf_sym:
            return 0.0
        try:
            # fetch 5d to handle weekends reliably
            df = yf.Ticker(yf_sym).history(period="5d", interval="1d")
            if df.empty:
                return 0.0
            return float(df["Close"].dropna().iloc[-1])
        except Exception as exc:
            log.warning(f"get_price failed for {raw}: {exc}")
            return 0.0

    def search_names(self, query: str, max_results: int = 20) -> list[dict]:
        """
        Search master list by symbol or name prefix.
        Returns list of {symbol, yf_symbol, display_name}.
        """
        q = query.strip().upper()
        results = []
        for nse_sym, yf_sym in self._master.items():
            if q in nse_sym:
                results.append({
                    "symbol": nse_sym,
                    "yf_symbol": yf_sym,
                    "display": f"{nse_sym} — ({yf_sym})",
                })
        # Also include index matches
        for k, v in _INDEX_MAP.items():
            if q in k:
                results.append({"symbol": k, "yf_symbol": v, "display": f"{k} — {v}"})
        return results[:max_results]

    # ── Master list management ──────────────────────────────────────────────

    def _load_master(self) -> None:
        """Load symbol master from CSV cache or build fresh from NSE."""
        if _CACHE_PATH.exists() and not self._is_stale(_CACHE_PATH):
            try:
                df = pd.read_csv(_CACHE_PATH)
                self._master = dict(zip(df["nse_symbol"], df["yf_symbol"]))
                log.info(f"Symbol master loaded from cache: {len(self._master)} symbols")
                return
            except Exception as exc:
                log.warning(f"Cache load failed: {exc}, rebuilding…")

        self._build_master()

    def _build_master(self) -> None:
        """Build symbol master from NSE via multiple sources."""
        log.info("Building symbol master from NSE…")
        master: dict[str, str] = {}

        # Source 1: nsepython
        try:
            from nsepython import nse_eq
            df = nse_eq("NIFTY 500")
            for sym in df["symbol"].dropna().unique():
                s = str(sym).strip().upper()
                master[s] = f"{s}.NS"
            log.info(f"nsepython: loaded {len(master)} symbols")
        except Exception as exc:
            log.warning(f"nsepython failed: {exc}")

        # Source 2: NSE direct CSV
        if len(master) < 100:
            try:
                import requests
                r = requests.get(
                    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                r.raise_for_status()
                from io import StringIO
                df = pd.read_csv(StringIO(r.text))
                df.columns = [c.strip() for c in df.columns]
                sym_col = "SYMBOL"
                if sym_col in df.columns:
                    for sym in df[sym_col].dropna().unique():
                        s = str(sym).strip().upper()
                        master[s] = f"{s}.NS"
                    log.info(f"NSE CSV: loaded {len(master)} symbols")
            except Exception as exc:
                log.warning(f"NSE CSV failed: {exc}")

        # Source 3: jugaad-trader
        if len(master) < 100:
            try:
                from jugaad_trader.nse import NSELive
                n = NSELive()
                data = n.equities("NSE")
                for item in data:
                    s = str(item.get("symbol", "")).strip().upper()
                    if s:
                        master[s] = f"{s}.NS"
                log.info(f"jugaad-trader: loaded {len(master)} symbols")
            except Exception as exc:
                log.warning(f"jugaad-trader failed: {exc}")

        # Always add static maps
        for k, v in _INDEX_MAP.items():
            master[k] = v
        for k, v in _OVERRIDE_MAP.items():
            master[k] = v

        # Minimum fallback: NIFTY50 hardcoded if all sources fail
        if len(master) < 30:
            log.warning("All dynamic sources failed. Using hardcoded NIFTY50 fallback.")
            for sym in [
                "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
                "ITC", "SBIN", "HINDUNILVR", "BHARTIARTL", "KOTAKBANK",
                "LT", "WIPRO", "AXISBANK", "MARUTI", "TATAMOTORS",
                "SUNPHARMA", "TITAN", "BAJFINANCE", "ASIANPAINT", "NESTLEIND",
                "ULTRACEMCO", "POWERGRID", "NTPC", "ONGC", "COALINDIA",
                "BAJAJFINSV", "TECHM", "DIVISLAB", "DRREDDY", "CIPLA",
                "GRASIM", "HEROMOTOCO", "EICHERMOT", "ADANIPORTS", "TATACONSUM",
                "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "BPCL",
                "INDUSINDBK", "APOLLOHOSP", "ADANIENT", "SBILIFE", "HDFCLIFE",
                "BRITANNIA", "SHRIRAMFIN", "LTIM", "HCLTECH", "M&M",
            ]:
                master[sym] = f"{sym}.NS"

        self._master = master
        self._save_master()
        log.info(f"Symbol master built: {len(self._master)} symbols")

    def _save_master(self) -> None:
        """Persist master to CSV for next run."""
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            df = pd.DataFrame(
                [{"nse_symbol": k, "yf_symbol": v} for k, v in self._master.items()]
            )
            df.to_csv(_CACHE_PATH, index=False)
        except Exception as exc:
            log.warning(f"Could not save symbol cache: {exc}")

    @staticmethod
    def _probe_yf(ticker: str) -> bool:
        """Fast probe: check if yfinance returns any data for ticker."""
        try:
            df = yf.Ticker(ticker).history(period="5d", interval="1d")
            return not df.empty
        except Exception:
            return False

    @staticmethod
    def _is_stale(path: Path) -> bool:
        from datetime import datetime, timedelta
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - mtime > timedelta(hours=_STALE_HOURS)
