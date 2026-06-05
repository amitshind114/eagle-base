"""Instrument search engine — Phase 1.

Searches the local SQLite master. Zero API calls.

Usage:
    from instruments.search import InstrumentSearch
    engine = InstrumentSearch()
    results = engine.search("RELIANCE")
    # Returns:
    #   RELIANCE-EQ    (equity)
    #   RELIANCE-FUT   (nearest future)
    #   RELIANCE 3000 CE  (options if loaded)
    #   RELIANCE 3000 PE
"""

from __future__ import annotations

from typing import List

from core.logger import get_logger
from .models import Instrument
from .storage import InstrumentStore
from .downloader import InstrumentDownloader

log = get_logger("instruments.search")


class InstrumentSearch:
    """Fast local search over instrument master."""

    def __init__(self) -> None:
        self._store = InstrumentStore()
        self._downloader = InstrumentDownloader()
        self._ensure_loaded()

    # ── Public API ────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 50) -> List[Instrument]:
        """
        Search by symbol, name, or underlying.
        Returns results ordered: EQ → IDX → FUT → CE → PE.
        Zero network calls.
        """
        if not query or len(query) < 1:
            return []
        results = self._store.search(query.strip(), limit=limit)
        log.debug(f"search('{query}') → {len(results)} results")
        return results

    def get(self, symbol: str) -> Instrument | None:
        """Exact symbol lookup. Returns None if not found."""
        return self._store.get_by_symbol(symbol)

    def list_segment(self, segment: str) -> List[Instrument]:
        """All instruments for a segment: EQ | FUT | CE | PE | IDX."""
        return self._store.list_by_segment(segment)

    def list_fo_underlyings(self) -> List[str]:
        """All F&O eligible underlying symbols."""
        return self._store.list_underlyings()

    def refresh(self, force: bool = False) -> None:
        """Refresh instrument master from NSE."""
        if force:
            self._downloader.refresh()
        else:
            self._downloader.refresh_if_stale()
        self._load_into_store()

    def stats(self) -> dict[str, int]:
        """Count of instruments per segment."""
        return self._store.count()

    # ── Private ───────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        counts = self._store.count()
        if not counts or counts.get("EQ", 0) < 100:
            log.info("Instrument master empty or small — loading from NSE…")
            self._downloader.refresh_if_stale()
            self._load_into_store()
        else:
            log.debug(f"Instrument master ready: {counts}")

    def _load_into_store(self) -> None:
        """Load equity + futures from downloader into SQLite."""
        try:
            equity = self._downloader.load_equity()
            self._store.insert_bulk(equity)
        except Exception as exc:
            log.error(f"Failed to load equity master: {exc}")

        try:
            futures = self._downloader.load_futures()
            self._store.insert_bulk(futures)
        except Exception as exc:
            log.error(f"Failed to load futures master: {exc}")

        log.info(f"Instrument store refreshed: {self._store.count()}")
