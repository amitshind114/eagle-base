"""Local Parquet cache provider — Phase 3.

Reads from the Parquet disk cache written by data/storage.py.
This is the fastest local fallback after an in-memory cache miss.

Path layout (mirrors data/storage.py):
    eagle_base/data/cache/{SYMBOL}/{interval}.parquet

Priority in DataManager:
    Yahoo → Angel → CSV → Parquet (read-only historical cache)
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from core.exceptions import DataFetchError
from core.logger import get_logger
from .base import DataProvider

log = get_logger("data.providers.parquet")

_DEFAULT_CACHE_DIR = Path(os.getenv(
    "EAGLE_CACHE_DIR",
    str(Path.home() / "eagle_base" / "data" / "cache")
))

_SUPPORTED_INTERVALS = [
    "1m", "3m", "5m", "15m", "30m", "1h",
    "1d", "1wk", "1mo",
]


class ParquetProvider(DataProvider):
    """Read OHLCV data from local Parquet cache files.

    These files are written by DataStorage (data/storage.py) after
    every successful fetch from a live provider.

    Args:
        cache_dir: Root of the Parquet cache.
                   Defaults to ~/eagle_base/data/cache/
                   or EAGLE_CACHE_DIR env var.
    """

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self._root = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR

    # ── DataProvider interface ─────────────────────────────────────────────

    def name(self) -> str:
        return "Local Parquet Cache"

    def is_available(self) -> bool:
        """Return True if any Parquet files exist in the cache dir."""
        return self._root.exists() and any(self._root.rglob("*.parquet"))

    def supported_intervals(self) -> List[str]:
        return _SUPPORTED_INTERVALS

    def fetch(
        self,
        symbol: str,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Read cached Parquet for symbol/interval and slice to date range."""
        self._validate_interval(interval)
        path = self._resolve_path(symbol, interval)
        if path is None:
            raise DataFetchError(
                f"[Parquet] No cache file for symbol='{symbol}' interval='{interval}'. "
                f"Fetch from a live provider first to populate the cache."
            )

        log.info(f"[Parquet] Reading cache: {path}")
        try:
            df = pd.read_parquet(path)
        except Exception as exc:
            raise DataFetchError(f"[Parquet] Failed to read {path}: {exc}") from exc

        df.index = pd.to_datetime(df.index)
        df = df[(df.index >= from_dt) & (df.index <= to_dt)]

        if df.empty:
            raise DataFetchError(
                f"[Parquet] No data in range {from_dt.date()}–{to_dt.date()} "
                f"for '{symbol}' interval='{interval}'."
            )
        return self._clean(df)

    def fetch_latest_price(self, symbol: str) -> float:
        """Return the latest close from the daily Parquet cache."""
        try:
            path = self._resolve_path(symbol, "1d")
            if path is None:
                return 0.0
            df = pd.read_parquet(path)
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            return float(df["Close"].iloc[-1])
        except Exception as exc:
            log.warning(f"[Parquet] fetch_latest_price failed for {symbol}: {exc}")
            return 0.0

    def list_cached(self) -> list[dict]:
        """Return all cached symbol/interval combos."""
        result = []
        if not self._root.exists():
            return result
        for sym_dir in sorted(self._root.iterdir()):
            if not sym_dir.is_dir():
                continue
            for pq_file in sorted(sym_dir.glob("*.parquet")):
                try:
                    df = pd.read_parquet(pq_file)
                    result.append({
                        "symbol": sym_dir.name,
                        "interval": pq_file.stem,
                        "rows": len(df),
                        "from": str(df.index.min()) if not df.empty else None,
                        "to": str(df.index.max()) if not df.empty else None,
                        "path": str(pq_file),
                    })
                except Exception:
                    pass
        return result

    # ── Helpers ────────────────────────────────────────────────────────────

    def _resolve_path(self, symbol: str, interval: str) -> Optional[Path]:
        sym = symbol.upper().replace(".NS", "").replace("-EQ", "")
        candidates = [
            self._root / sym / f"{interval}.parquet",
            self._root / sym.lower() / f"{interval}.parquet",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None
