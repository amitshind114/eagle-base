"""Angel One ScripMaster — token resolver.

Downloads the ScripMaster JSON once daily and caches it locally.
Exposes resolve_token(nse_symbol, exchange) for every broker call
that needs a numeric symboltoken.

Never import anything from this file that triggers a network call
at import time — the load is lazy (first resolve_token call).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

from core.exceptions import InstrumentNotFoundError

log = logging.getLogger("instruments.angel_master")

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com"
    "/OpenAPI_File/files/OpenAPIScripMaster.json"
)
CACHE_PATH = Path("eagle_base/data/angel_master.json")
STALE_HOURS = 24


# ── Staleness check ───────────────────────────────────────────────────────────

def _is_stale(path: Path, hours: int = STALE_HOURS) -> bool:
    if not path.exists():
        return True
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - mtime > timedelta(hours=hours)


# ── Download / load ───────────────────────────────────────────────────────────

def load_master(cache_path: Path = CACHE_PATH) -> pd.DataFrame:
    """Return ScripMaster DataFrame, fetching from Angel CDN if stale.

    Columns of interest: token, symbol, name, exch_seg, instrumenttype, lotsize
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if _is_stale(cache_path):
        log.info("[angel_master] Fetching ScripMaster from Angel CDN...")
        try:
            r = httpx.get(SCRIP_MASTER_URL, timeout=30)
            r.raise_for_status()
            cache_path.write_text(r.text, encoding="utf-8")
            log.info("[angel_master] ScripMaster cached to %s", cache_path)
        except Exception as exc:
            if cache_path.exists():
                log.warning(
                    "[angel_master] Fetch failed (%s) — using stale cache.", exc
                )
            else:
                raise RuntimeError(
                    f"Cannot fetch Angel ScripMaster and no cache exists: {exc}"
                ) from exc

    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    df = pd.DataFrame(raw)
    # Normalise column names to lowercase
    df.columns = [c.lower().strip() for c in df.columns]
    log.debug("[angel_master] Loaded %d instruments from ScripMaster.", len(df))
    return df


# ── Module-level lazy singleton ───────────────────────────────────────────────

_MASTER_DF: Optional[pd.DataFrame] = None


def _get_master() -> pd.DataFrame:
    global _MASTER_DF
    if _MASTER_DF is None:
        _MASTER_DF = load_master()
    return _MASTER_DF


def invalidate_cache() -> None:
    """Force a fresh download on the next resolve call."""
    global _MASTER_DF
    _MASTER_DF = None
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()
        log.info("[angel_master] Cache invalidated.")


# ── Primary resolver ──────────────────────────────────────────────────────────

def resolve_token(
    nse_symbol: str,
    exchange: str = "NSE",
    instrument_type: str = "",
) -> str:
    """Return Angel One numeric token string for an NSE/BSE/NFO ticker.

    Args:
        nse_symbol      : Raw NSE symbol e.g. 'RELIANCE' or 'NIFTY'
        exchange        : 'NSE' | 'BSE' | 'NFO' | 'MCX'
        instrument_type : '' (equity) | 'FUTSTK' | 'OPTSTK' | 'FUTIDX' | 'OPTIDX'

    Returns:
        Numeric token string e.g. '2885'

    Raises:
        InstrumentNotFoundError if not found after all lookup strategies.
    """
    df = _get_master()
    sym = nse_symbol.strip().upper()
    exch = exchange.strip().upper()

    # Strategy 1: exact name match on the correct exchange + instrument type
    mask = (df["exch_seg"] == exch) & (df["name"] == sym)
    if instrument_type:
        mask &= df["instrumenttype"] == instrument_type
    else:
        # Equity: instrumenttype is empty string or 'EQ'
        mask &= df["instrumenttype"].isin(["", "EQ"])

    rows = df[mask]
    if not rows.empty:
        return str(rows.iloc[0]["token"])

    # Strategy 2: match by 'symbol' column (e.g. 'RELIANCE-EQ')
    mask2 = (df["exch_seg"] == exch) & (df["symbol"].str.startswith(sym))
    rows2 = df[mask2]
    if not rows2.empty:
        return str(rows2.iloc[0]["token"])

    raise InstrumentNotFoundError(
        f"No Angel One token found for '{nse_symbol}' on {exchange} "
        f"(instrument_type='{instrument_type}')"
    )


def resolve_lot_size(nse_symbol: str, exchange: str = "NFO") -> int:
    """Return lot size for an F&O instrument from ScripMaster."""
    df = _get_master()
    sym = nse_symbol.strip().upper()
    mask = (df["exch_seg"] == exchange.upper()) & (df["name"] == sym)
    rows = df[mask]
    if not rows.empty and "lotsize" in rows.columns:
        try:
            return int(rows.iloc[0]["lotsize"])
        except (ValueError, TypeError):
            pass
    return 1  # safe default for equity


def get_instrument_details(token: str) -> dict:
    """Reverse lookup — token → full instrument row as dict."""
    df = _get_master()
    rows = df[df["token"] == str(token)]
    if rows.empty:
        raise InstrumentNotFoundError(f"No instrument found for token '{token}'")
    return rows.iloc[0].to_dict()
