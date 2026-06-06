"""Local CSV provider — Phase 3.

Reads OHLCV data from local CSV files.
Useful for:
  - Historical data imports
  - Offline backtesting
  - Custom / proprietary data sources

Expected directory layout:
    eagle_base/data/csv_store/{SYMBOL}/{interval}.csv
    e.g. eagle_base/data/csv_store/RELIANCE/1d.csv

Expected CSV columns (case-insensitive):
    datetime/date/timestamp, open, high, low, close, volume
    OR: Date, Open, High, Low, Close, Volume (standard OHLCV)
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from core.logger import get_logger
from core.exceptions import DataFetchError
from .base import DataProvider

log = get_logger("data.providers.csv")

_DEFAULT_CSV_DIR = Path(os.getenv(
    "EAGLE_CSV_DIR",
    str(Path.home() / "eagle_base" / "data" / "csv_store")
))

_SUPPORTED_INTERVALS = [
    "1m", "3m", "5m", "15m", "30m", "1h",
    "1d", "1wk", "1mo",
]

# Column name normalisation map
_COL_MAP = {
    "datetime": "datetime", "date": "datetime", "timestamp": "datetime",
    "time": "datetime", "index": "datetime",
    "open": "Open", "high": "High", "low": "Low",
    "close": "Close", "volume": "Volume",
}


class CSVProvider(DataProvider):
    """Read OHLCV data from local CSV files.

    Args:
        csv_dir: Root directory for CSV files.
                 Defaults to ~/eagle_base/data/csv_store/
                 or EAGLE_CSV_DIR env var.
    """

    def __init__(self, csv_dir: Optional[Path] = None) -> None:
        self._root = Path(csv_dir) if csv_dir else _DEFAULT_CSV_DIR

    # ── DataProvider interface ─────────────────────────────────────────────

    def name(self) -> str:
        return "Local CSV"

    def is_available(self) -> bool:
        """Return True if the CSV root directory exists and has files."""
        return self._root.exists() and any(self._root.rglob("*.csv"))

    def supported_intervals(self) -> List[str]:
        return _SUPPORTED_INTERVALS

    def fetch(
        self,
        symbol: str,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Read CSV for symbol/interval and slice to from_dt..to_dt."""
        self._validate_interval(interval)
        path = self._resolve_path(symbol, interval)
        if path is None:
            raise DataFetchError(
                f"[CSV] No file found for symbol='{symbol}' interval='{interval}'. "
                f"Expected: {self._root / symbol.upper() / (interval + '.csv')}"
            )

        log.info(f"[CSV] Reading {path}")
        df = self._load_csv(path)

        # Slice to requested date range
        df = df[(df.index >= from_dt) & (df.index <= to_dt)]
        if df.empty:
            raise DataFetchError(
                f"[CSV] No data in range {from_dt.date()}–{to_dt.date()} "
                f"for '{symbol}' in {path}."
            )
        return self._clean(df)

    def fetch_latest_price(self, symbol: str) -> float:
        """Return the latest close from the daily CSV file."""
        try:
            path = self._resolve_path(symbol, "1d")
            if path is None:
                return 0.0
            df = self._load_csv(path)
            return float(df["Close"].iloc[-1])
        except Exception as exc:
            log.warning(f"[CSV] fetch_latest_price failed for {symbol}: {exc}")
            return 0.0

    def list_available(self) -> list[dict]:
        """Return all available symbol/interval combos in the CSV store."""
        result = []
        if not self._root.exists():
            return result
        for sym_dir in sorted(self._root.iterdir()):
            if not sym_dir.is_dir():
                continue
            for csv_file in sorted(sym_dir.glob("*.csv")):
                result.append({
                    "symbol": sym_dir.name,
                    "interval": csv_file.stem,
                    "path": str(csv_file),
                })
        return result

    # ── Helpers ────────────────────────────────────────────────────────────

    def _resolve_path(self, symbol: str, interval: str) -> Optional[Path]:
        sym = symbol.upper().replace(".NS", "").replace("-EQ", "")
        candidates = [
            self._root / sym / f"{interval}.csv",
            self._root / sym.lower() / f"{interval}.csv",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    @staticmethod
    def _load_csv(path: Path) -> pd.DataFrame:
        """Load CSV → normalised DataFrame with DatetimeIndex."""
        df = pd.read_csv(path)
        # Normalise column names
        df.columns = [
            _COL_MAP.get(c.lower().strip(), c.strip())
            for c in df.columns
        ]
        # Set datetime index
        dt_col = next(
            (c for c in df.columns if c == "datetime"),
            None
        )
        if dt_col:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
        else:
            # Try using the first column as index
            df.index = pd.to_datetime(df.index)
        return df
