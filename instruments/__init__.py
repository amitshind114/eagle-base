"""Instruments package — Phase 1.

Public surface:
    InstrumentStore     — high-level Instrument-object API
    InstrumentStorage   — low-level raw-dict API
    InstrumentResolver  — symbol → Instrument resolver
    angel_master        — Angel One ScripMaster helpers
    to_yf_symbol        — ensure correct Yahoo Finance suffix
    to_angel_symbol     — strip .NS/.BO for Angel One calls
"""

from instruments.storage import InstrumentStore, InstrumentStorage
from instruments.resolver import InstrumentResolver, to_yf_symbol, to_angel_symbol
from instruments.angel_master import (
    load_master,
    resolve_token,
    resolve_lot_size,
    get_instrument_details,
    invalidate_cache,
)

__all__ = [
    # Storage
    "InstrumentStore",
    "InstrumentStorage",
    # Resolver
    "InstrumentResolver",
    "to_yf_symbol",
    "to_angel_symbol",
    # Angel Master
    "load_master",
    "resolve_token",
    "resolve_lot_size",
    "get_instrument_details",
    "invalidate_cache",
]
