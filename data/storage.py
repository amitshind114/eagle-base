"""Parquet Storage — Phase 2.

Persistent disk cache for OHLCV data.
One Parquet file per symbol per interval.
Far faster than re-fetching from yfinance on every run.

Structure:
  eagle_base/data/cache/
    RELIANCE.NS/
      1d.parquet
      5m.parquet
      15m.parquet
    TCS.NS/
      1d.parquet
    ^NSEI/
      1d.parquet

Usage:
    from data.storage import ParquetStorage
    store = ParquetStorage()
    store.write("RELIANCE.NS", "5m", df)
    df = store.read("RELIANCE.NS", "5m")
    store.append("RELIANCE.NS", "1d", new_bars)
    store.list_cached()  → [("RELIANCE.NS","1d"), ("TCS.NS","1d"), ...]
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from core.logger import get_logger

log = get_logger("data.storage")

_CACHE_ROOT = Path("eagle_base/data/cache")

# TTL per interval: how long before we consider cached data stale
_TTL: dict[str, timedelta] = {
    "1m":  timedelta(minutes=5),
    "3m":  timedelta(minutes=5),
    "5m":  timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h":  timedelta(hours=1),
    "1d":  timedelta(hours=6),
    "1wk": timedelta(days=1),
    "1mo": timedelta(days=7),
}


class ParquetStorage:
    """Parquet-backed OHLCV storage with TTL-aware staleness check."""

    def __init__(self, root: Path = _CACHE_ROOT) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # ── Write ─────────────────────────────────────────────────────────────

    def write(self, symbol: str, interval: str, df: pd.DataFrame) -> None:
        """Write (overwrite) cached data for symbol+interval."""
        if df is None or df.empty:
            return
        path = self._path(symbol, interval)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, engine="pyarrow", compression="snappy")
        log.debug(f"Cached {len(df)} bars → {path}")

    def append(self, symbol: str, interval: str, new_df: pd.DataFrame) -> None:
        """Append new bars to existing cache, dedup by timestamp."""
        existing = self.read(symbol, interval)
        if existing is None or existing.empty:
            self.write(symbol, interval, new_df)
            return
        combined = pd.concat([existing, new_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
        self.write(symbol, interval, combined)
        log.debug(f"Appended {len(new_df)} bars for {symbol}/{interval}. Total: {len(combined)}")

    # ── Read ──────────────────────────────────────────────────────────────

    def read(
        self,
        symbol: str,
        interval: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Read cached data. Returns None if not cached."""
        path = self._path(symbol, interval)
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path, engine="pyarrow")
            df.index = pd.to_datetime(df.index)
            if from_date:
                df = df[df.index >= pd.Timestamp(from_date)]
            if to_date:
                df = df[df.index <= pd.Timestamp(to_date)]
            return df if not df.empty else None
        except Exception as exc:
            log.warning(f"Read cache failed for {symbol}/{interval}: {exc}")
            return None

    def is_stale(self, symbol: str, interval: str) -> bool:
        """True if cached file is older than the TTL for this interval."""
        path = self._path(symbol, interval)
        if not path.exists():
            return True
        ttl = _TTL.get(interval, timedelta(hours=1))
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return datetime.now() - mtime > ttl

    def invalidate(self, symbol: str, interval: Optional[str] = None) -> None:
        """Delete cached file(s) for a symbol. If interval is None, clears all."""
        if interval:
            path = self._path(symbol, interval)
            if path.exists():
                path.unlink()
                log.info(f"Invalidated cache: {path}")
        else:
            sym_dir = self._sym_dir(symbol)
            if sym_dir.exists():
                for f in sym_dir.glob("*.parquet"):
                    f.unlink()
                log.info(f"Invalidated all cache for {symbol}")

    def list_cached(self) -> List[Tuple[str, str]]:
        """List all cached (symbol, interval) pairs."""
        results = []
        for sym_dir in self.root.iterdir():
            if sym_dir.is_dir():
                for f in sym_dir.glob("*.parquet"):
                    interval = f.stem
                    results.append((sym_dir.name, interval))
        return sorted(results)

    def cache_info(self) -> List[dict]:
        """Detailed info about all cached entries."""
        rows = []
        for sym, interval in self.list_cached():
            path = self._path(sym, interval)
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            stale = self.is_stale(sym, interval)
            try:
                df = pd.read_parquet(path)
                bars = len(df)
                first = str(df.index[0])[:19] if bars else "?"
                last  = str(df.index[-1])[:19] if bars else "?"
            except Exception:
                bars, first, last = 0, "?", "?"
            rows.append({
                "symbol": sym,
                "interval": interval,
                "bars": bars,
                "first": first,
                "last": last,
                "cached_at": mtime.strftime("%Y-%m-%d %H:%M"),
                "stale": stale,
            })
        return rows

    # ── Internals ─────────────────────────────────────────────────────────

    def _safe_sym(self, symbol: str) -> str:
        """Convert symbol to filesystem-safe directory name."""
        return symbol.replace("/", "_").replace("\\", "_").replace(":", "_")

    def _sym_dir(self, symbol: str) -> Path:
        return self.root / self._safe_sym(symbol)

    def _path(self, symbol: str, interval: str) -> Path:
        return self._sym_dir(symbol) / f"{interval}.parquet"
