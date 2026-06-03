"""Options domain models."""

from __future__ import annotations

from pydantic import BaseModel


class OptionContract(BaseModel):
    strike: float
    option_type: str  # 'call' or 'put'
    spot: float
    expiry_days: int
    iv: float
    ltp: float
    delta: float
    gamma: float
    theta: float
    vega: float
    moneyness: str  # 'ITM', 'ATM', 'OTM'
