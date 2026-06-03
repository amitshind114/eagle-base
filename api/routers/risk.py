"""Risk API router."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from risk.manager import RiskManager

router = APIRouter()


class PositionSizeRequest(BaseModel):
    symbol: str
    entry_price: float
    stop_loss_points: float
    risk_pct: float = 1.0
    capital: float = 500_000.0


@router.post("/position-size")
def position_size(req: PositionSizeRequest):
    rm = RiskManager(capital=req.capital)
    result = rm.position_size(
        req.symbol, req.entry_price, req.stop_loss_points, req.risk_pct
    )
    return result.model_dump()
