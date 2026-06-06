"""Angel One instrument token map — Phase 8 Live Safety.

Maps NSE symbols to Angel One instrument tokens required for order placement.
Token map is cached locally so live orders never fail due to a missing token.

Usage:
    from instruments.token_map import get_token, refresh_if_stale

    token = get_token("RELIANCE")          # "2885"
    token = get_token("TCS")               # "11536"
    refresh_if_stale()                     # no-op if cache < 24h old

Raises:
    ValueError  : symbol not found in token map after refresh
    RuntimeError: SmartAPI unavailable AND no local cache exists
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from core.logger import get_logger

log = get_logger("instruments.token_map")

# ── Cache location ────────────────────────────────────────────────────────────
_CACHE_DIR  = Path(os.environ.get("EAGLE_DATA_DIR", "eagle_base/data"))
_CACHE_FILE = _CACHE_DIR / "token_map.json"
_TTL_SECS   = 86_400  # 24 hours

# In-memory store: {"RELIANCE": "2885", ...}
_token_map: dict[str, str] = {}
_loaded_at: float = 0.0


# ── Download from Angel One SmartAPI ─────────────────────────────────────────

def download_instrument_master() -> dict[str, str]:
    """Fetch NSE instrument list from Angel One SmartAPI.

    Returns:
        dict mapping SYMBOL (str) → token (str)

    Raises:
        RuntimeError: if SmartAPI is not installed or call fails.
    """
    try:
        from SmartApi import SmartConnect  # pip install smartapi-python
    except ImportError as exc:
        raise RuntimeError(
            "smartapi-python not installed. "
            "Run: pip install smartapi-python"
        ) from exc

    api_key = os.environ.get("ANGEL_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "ANGEL_API_KEY env var not set. "
            "Cannot download instrument master without credentials."
        )

    log.info("[token_map] Downloading NSE instrument master from Angel One...")
    try:
        client = SmartConnect(api_key=api_key)
        instruments = client.instruments("NSE")  # returns list of dicts
    except Exception as exc:
        raise RuntimeError(f"[token_map] SmartAPI.instruments() failed: {exc}") from exc

    if not instruments:
        raise RuntimeError("[token_map] SmartAPI returned empty instrument list.")

    mapping: dict[str, str] = {}
    for row in instruments:
        symbol = str(row.get("symbol", "")).strip().upper()
        token  = str(row.get("token", "")).strip()
        if symbol and token:
            mapping[symbol] = token

    log.info(f"[token_map] Loaded {len(mapping)} NSE instruments from SmartAPI.")
    return mapping


# ── Cache I/O ─────────────────────────────────────────────────────────────────

def _save_cache(mapping: dict[str, str]) -> None:
    """Write token map + timestamp to disk."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": time.time(), "tokens": mapping}
    _CACHE_FILE.write_text(json.dumps(payload, indent=2))
    log.info(f"[token_map] Cache written: {_CACHE_FILE} ({len(mapping)} tokens)")


def _load_cache() -> Optional[dict[str, str]]:
    """Load token map from disk cache. Returns None if file missing or corrupt."""
    if not _CACHE_FILE.exists():
        return None
    try:
        payload  = json.loads(_CACHE_FILE.read_text())
        mapping  = payload.get("tokens", {})
        saved_at = float(payload.get("timestamp", 0.0))
        age_h    = (time.time() - saved_at) / 3600
        log.info(f"[token_map] Cache loaded: {len(mapping)} tokens (age {age_h:.1f}h)")
        return mapping
    except Exception as exc:
        log.warning(f"[token_map] Cache load failed: {exc}")
        return None


def _cache_age_secs() -> float:
    """Return seconds since cache was written. Returns infinity if no cache."""
    if not _CACHE_FILE.exists():
        return float("inf")
    try:
        payload = json.loads(_CACHE_FILE.read_text())
        return time.time() - float(payload.get("timestamp", 0.0))
    except Exception:
        return float("inf")


# ── Public API ────────────────────────────────────────────────────────────────

def refresh_if_stale() -> None:
    """Refresh token map from SmartAPI if cache is older than 24h.

    Called by LiveExecutor.connect() to ensure token map is ready before
    any orders are placed.

    If SmartAPI is unavailable but a valid local cache exists, the cache
    is used. If neither is available, raises RuntimeError.
    """
    global _token_map, _loaded_at

    age = _cache_age_secs()
    if age < _TTL_SECS and _token_map:
        log.debug(f"[token_map] Cache is fresh ({age/3600:.1f}h old). Skipping refresh.")
        return

    # Try to download fresh data
    try:
        mapping = download_instrument_master()
        _save_cache(mapping)
        _token_map = mapping
        _loaded_at = time.time()
        return
    except Exception as exc:
        log.warning(f"[token_map] Download failed: {exc}. Falling back to disk cache.")

    # Fall back to disk cache
    cached = _load_cache()
    if cached:
        _token_map = cached
        _loaded_at = time.time()
        return

    # No cache, no download — hard fail
    raise RuntimeError(
        "Instrument token map unavailable — cannot place orders safely. "
        "Ensure ANGEL_API_KEY is set and network is reachable, "
        f"or place a valid token_map.json at: {_CACHE_FILE}"
    )


def get_token(symbol: str) -> str:
    """Return the Angel One instrument token for a given NSE symbol.

    Args:
        symbol: NSE symbol, e.g. 'RELIANCE', 'TCS', 'HDFCBANK'
                .NS suffix is stripped automatically.

    Returns:
        Instrument token string (e.g. '2885').

    Raises:
        ValueError : Symbol not found in token map.
        RuntimeError: Token map is empty (never loaded / download failed).
    """
    global _token_map

    sym = symbol.strip().upper().replace(".NS", "").replace("-EQ", "")

    # Load from disk if not yet in memory
    if not _token_map:
        cached = _load_cache()
        if cached:
            _token_map = cached

    if not _token_map:
        raise RuntimeError(
            "Token map is empty. Call refresh_if_stale() first, "
            "or ensure token_map.json exists at: " + str(_CACHE_FILE)
        )

    token = _token_map.get(sym)
    if not token:
        raise ValueError(
            f"No instrument token for '{sym}'. "
            "Run refresh_if_stale() to update the instrument master, "
            "or check the symbol is listed on NSE."
        )

    return token


def list_symbols() -> list[str]:
    """Return all symbols in the loaded token map."""
    return sorted(_token_map.keys())


def token_count() -> int:
    """Return number of tokens loaded in memory."""
    return len(_token_map)
