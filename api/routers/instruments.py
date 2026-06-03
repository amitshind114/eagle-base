"""Instruments API router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from instruments.registry import InstrumentRegistry
from core.exceptions import InstrumentNotFoundError

router = APIRouter()
registry = InstrumentRegistry()


@router.get("/search")
def search(q: str = ""):
    results = registry.search(q)
    return {"count": len(results), "results": [i.model_dump() for i in results]}


@router.get("/{symbol}")
def get_instrument(symbol: str):
    try:
        inst = registry.get(symbol.upper())
        return inst.model_dump()
    except InstrumentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
