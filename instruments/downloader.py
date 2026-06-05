"""NSE Instrument Master Downloader — Phase 1.

Downloads equity master (EQUITY_L.csv) and F&O lot size data from NSE.
Stores locally so search never needs an API call.

Usage:
    from instruments.downloader import InstrumentDownloader
    dl = InstrumentDownloader()
    dl.refresh()          # force download
    dl.refresh_if_stale() # only if > 1 day old
"""

from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import requests

from core.logger import get_logger
from .models import Instrument

log = get_logger("instruments.downloader")

# NSE public endpoints
_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
_FO_LOT_URL = "https://archives.nseindia.com/content/fo/fo_mktlots.csv"

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

_DATA_DIR = Path("eagle_base/data")
_EQUITY_CSV = _DATA_DIR / "equity_master.csv"
_FO_CSV = _DATA_DIR / "fo_lots.csv"
_STAMP_FILE = _DATA_DIR / ".instrument_stamp"

_STALE_HOURS = 24


class InstrumentDownloader:
    """Downloads and caches NSE instrument master files."""

    def __init__(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public ───────────────────────────────────────────────────────────

    def refresh_if_stale(self) -> None:
        """Download only if local cache is older than _STALE_HOURS."""
        if self._is_stale():
            log.info("Instrument master is stale — refreshing…")
            self.refresh()
        else:
            log.debug("Instrument master is fresh, skipping download.")

    def refresh(self) -> None:
        """Force download equity + F&O master files."""
        self._download(_EQUITY_URL, _EQUITY_CSV, "equity master")
        self._download(_FO_LOT_URL, _FO_CSV, "F&O lots")
        self._write_stamp()

    def load_equity(self) -> List[Instrument]:
        """Parse equity master CSV → list[Instrument]."""
        if not _EQUITY_CSV.exists():
            log.warning("Equity master not found — running refresh.")
            self.refresh()

        instruments: List[Instrument] = []
        with open(_EQUITY_CSV, encoding="utf-8", errors="ignore") as fh:
            reader = csv.DictReader(fh)
            # Normalize headers: strip spaces
            reader.fieldnames = [f.strip() for f in (reader.fieldnames or [])]
            fo_lots = self._load_fo_lots()
            for row in reader:
                sym = row.get("SYMBOL", "").strip()
                name = row.get("NAME OF COMPANY", "").strip()
                isin = row.get("ISIN NUMBER", "").strip()
                if not sym:
                    continue
                instruments.append(
                    Instrument(
                        symbol=f"{sym}-EQ",
                        name=name,
                        exchange="NSE",
                        segment="EQ",
                        isin=isin,
                        lot_size=fo_lots.get(sym, {}).get("lot_size", 1),
                        tick_size=0.05,
                        underlying=sym,
                        yf_symbol=f"{sym}.NS",
                    )
                )
        log.info(f"Loaded {len(instruments)} equity instruments.")
        return instruments

    def load_futures(self) -> List[Instrument]:
        """Build futures instruments from F&O lot data."""
        if not _FO_CSV.exists():
            self.refresh()
        fo_lots = self._load_fo_lots()
        instruments: List[Instrument] = []
        from datetime import date
        # Use current month + next 2 monthly expiries as placeholders
        # Real expiry dates come from NSE option chain (Phase 1 enhancement)
        for sym, info in fo_lots.items():
            instruments.append(
                Instrument(
                    symbol=f"{sym}-FUT",
                    name=info.get("name", sym),
                    exchange="NSE",
                    segment="FUT",
                    underlying=sym,
                    lot_size=info.get("lot_size", 1),
                    yf_symbol=f"{sym}.NS",
                )
            )
        log.info(f"Loaded {len(instruments)} futures instruments.")
        return instruments

    # ── Private ──────────────────────────────────────────────────────────

    def _download(self, url: str, dest: Path, label: str) -> None:
        for attempt in range(1, 4):
            try:
                resp = requests.get(url, headers=_HEADERS, timeout=15)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                log.info(f"Downloaded {label} → {dest}")
                return
            except Exception as exc:
                log.warning(f"Download attempt {attempt}/3 failed for {label}: {exc}")
                time.sleep(2 ** attempt)
        log.error(f"All attempts failed for {label}. Using stale cache if available.")

    def _load_fo_lots(self) -> dict[str, dict]:
        """Parse fo_mktlots.csv → {symbol: {lot_size, name}}."""
        fo: dict[str, dict] = {}
        if not _FO_CSV.exists():
            return fo
        with open(_FO_CSV, encoding="utf-8", errors="ignore") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
        # NSE fo_mktlots format: Symbol in col 1, lot size in col 2
        for row in rows[1:]:
            if len(row) < 3:
                continue
            sym = row[1].strip()
            try:
                lot = int(row[2].strip().replace(",", ""))
            except ValueError:
                lot = 1
            if sym:
                fo[sym] = {"lot_size": lot, "name": sym}
        return fo

    def _is_stale(self) -> bool:
        if not _STAMP_FILE.exists():
            return True
        mtime = datetime.fromtimestamp(_STAMP_FILE.stat().st_mtime)
        return datetime.now() - mtime > timedelta(hours=_STALE_HOURS)

    def _write_stamp(self) -> None:
        _STAMP_FILE.write_text(datetime.now().isoformat())
