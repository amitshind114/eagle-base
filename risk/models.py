"""Risk domain models."""

from __future__ import annotations

from pydantic import BaseModel


class PositionSizeResult(BaseModel):
    symbol: str
    entry_price: float
    stop_loss_price: float
    stop_loss_points: float
    risk_amount: float
    quantity: int
    exposure: float
    exposure_pct: float
    is_within_limits: bool
    warnings: list[str] = []


class RiskMetrics(BaseModel):
    portfolio_value: float
    var_95: float
    var_99: float
    max_drawdown_pct: float
    sharpe_ratio: float
    open_positions: int
    daily_pnl: float
    margin_used_pct: float
