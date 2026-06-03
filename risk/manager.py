"""Risk management engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from core.config import settings
from core.exceptions import RiskBreachError
from core.logger import get_logger
from .models import PositionSizeResult, RiskMetrics

log = get_logger("risk.manager")


class RiskManager:
    """Compute position sizes, VaR, and enforce risk limits."""

    def __init__(self, capital: float | None = None) -> None:
        self.capital = capital or settings.default_capital

    def position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss_points: float,
        risk_pct: float | None = None,
    ) -> PositionSizeResult:
        """Calculate position size based on fixed fractional risk."""
        risk_pct = risk_pct or settings.max_risk_per_trade_pct
        risk_amount = self.capital * risk_pct / 100
        qty = int(risk_amount / stop_loss_points) if stop_loss_points > 0 else 0
        exposure = qty * entry_price
        exposure_pct = exposure / self.capital * 100
        warnings = []
        if exposure_pct > settings.max_position_exposure_pct:
            warnings.append(f"Exposure {exposure_pct:.1f}% exceeds limit {settings.max_position_exposure_pct}%")
        result = PositionSizeResult(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss_price=entry_price - stop_loss_points,
            stop_loss_points=stop_loss_points,
            risk_amount=risk_amount,
            quantity=qty,
            exposure=exposure,
            exposure_pct=round(exposure_pct, 2),
            is_within_limits=len(warnings) == 0,
            warnings=warnings,
        )
        log.info(f"Position size for {symbol}: qty={qty} exposure=₹{exposure:,.0f} ({exposure_pct:.1f}%)")
        return result

    def compute_var(
        self,
        returns: pd.Series,
        confidence: float = 0.95,
        portfolio_value: float | None = None,
    ) -> float:
        """Parametric VaR using normal distribution."""
        pv = portfolio_value or self.capital
        z = norm.ppf(confidence)
        return float(pv * z * returns.std())

    def check_limits(
        self,
        daily_pnl: float,
        open_positions: int,
        current_drawdown_pct: float,
        margin_used_pct: float,
    ) -> list[str]:
        """Return list of breached risk limits."""
        breaches = []
        if abs(daily_pnl) > settings.max_daily_loss:
            breaches.append(f"Daily loss ₹{abs(daily_pnl):,.0f} exceeds limit ₹{settings.max_daily_loss:,.0f}")
        if open_positions > settings.max_open_positions:
            breaches.append(f"Open positions {open_positions} exceeds limit {settings.max_open_positions}")
        if abs(current_drawdown_pct) > settings.max_drawdown_pct:
            breaches.append(f"Drawdown {current_drawdown_pct:.1f}% exceeds limit {settings.max_drawdown_pct}%")
        if margin_used_pct > 80:
            breaches.append(f"Margin utilisation {margin_used_pct:.1f}% is critically high")
        if breaches:
            for b in breaches:
                log.warning(f"RISK BREACH: {b}")
        return breaches
