"""Instrument domain model."""

from __future__ import annotations

from pydantic import BaseModel


class Instrument(BaseModel):
    symbol: str
    name: str
    sector: str
    market: str = "NSE"
    asset_type: str = "EQ"  # EQ, FUT, OPT, IDX
    lot_size: int = 1
    tick_size: float = 0.05
