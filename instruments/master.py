"""Instrument Master Loader — Priority 2.

Loads the full Angel One instrument master JSON (~20,000+ instruments)
and populates the InstrumentResolver registry.

Angel One master URL:
https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json

Usage:
    from instruments.resolver import InstrumentResolver
    from instruments.master import InstrumentMaster

    resolver = InstrumentResolver()
    master = InstrumentMaster(resolver)
    count = master.load_from_url()
    print(f"Loaded {count} instruments")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from core.logger import logger
from instruments.resolver import Instrument

if TYPE_CHECKING:
    from instruments.resolver import InstrumentResolver

MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
MASTER_CACHE = Path(__file__).parent / "master_cache.json"


class InstrumentMaster:
    """Downloads and loads Angel One full instrument master."""

    def __init__(self, resolver: "InstrumentResolver"):
        self.resolver = resolver

    def load_from_url(self, force_refresh: bool = False) -> int:
        """Download Angel One master JSON and load into resolver.

        Args:
            force_refresh: Re-download even if local cache exists

        Returns:
            Number of instruments loaded
        """
        if MASTER_CACHE.exists() and not force_refresh:
            logger.info("[master] Loading from local cache...")
            return self._load_from_file(MASTER_CACHE)

        logger.info("[master] Downloading Angel One instrument master...")
        try:
            resp = requests.get(MASTER_URL, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            MASTER_CACHE.write_text(json.dumps(data), encoding="utf-8")
            logger.info(f"[master] Downloaded {len(data)} instruments, cached locally")
            return self._parse_and_register(data)
        except Exception as e:
            logger.error(f"[master] Failed to download: {e}")
            return 0

    def _load_from_file(self, path: Path) -> int:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return self._parse_and_register(data)
        except Exception as e:
            logger.error(f"[master] Failed to load from file: {e}")
            return 0

    def _parse_and_register(self, data: list[dict]) -> int:
        """Parse Angel One master JSON and register all instruments."""
        count = 0
        for item in data:
            try:
                instrument = Instrument(
                    symbol=item.get("symbol", ""),
                    token=item.get("token", ""),
                    exchange=item.get("exch_seg", ""),
                    instrument_type=item.get("instrumenttype", "EQ"),
                    name=item.get("name", ""),
                    lot_size=int(item.get("lotsize", 1)),
                    tick_size=float(item.get("tick_size", 0.05)),
                    expiry=item.get("expiry", ""),
                    strike=float(item.get("strike", 0)) / 100,
                )
                self.resolver.register(instrument)
                count += 1
            except Exception:
                continue
        logger.info(f"[master] Registered {count} instruments from master")
        return count
