"""Risk and performance metrics — pure math, no external dependencies.

All functions accept a list of net PnL values (one per trade) or a
sequence of portfolio equity values and return a scalar or dict.

Functions are stateless and side-effect free — safe to call from
backtesting, paper trading, and live reporting.

Usage:
    from risk.metrics import compute_metrics

    stats = compute_metrics(
        pnl_series=trade_log.net_pnls(),
        equity_curve=equity_values,
        risk_free_rate=0.065,   # MIBOR/repo rate
    )
"""

from __future__ import annotations

import math
from typing import Sequence


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float], ddof: int = 1) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - ddof)
    return math.sqrt(variance)


def sharpe_ratio(
    returns: Sequence[float],
    risk_free_rate: float = 0.065,
    periods_per_year: int = 252,
) -> float:
    """Annualised Sharpe ratio.

    returns:          per-trade or per-bar return as fraction (0.01 = 1%).
    risk_free_rate:   annual risk-free rate (India repo ~6.5%).
    periods_per_year: 252 for daily bars, 365*375 for 1-min intraday.
    """
    if len(returns) < 2:
        return 0.0
    daily_rf = risk_free_rate / periods_per_year
    excess   = [r - daily_rf for r in returns]
    std      = _std(excess)
    if std == 0:
        return 0.0
    return (_mean(excess) / std) * math.sqrt(periods_per_year)


def sortino_ratio(
    returns: Sequence[float],
    risk_free_rate: float = 0.065,
    periods_per_year: int = 252,
) -> float:
    """Annualised Sortino ratio (penalises only downside volatility)."""
    if len(returns) < 2:
        return 0.0
    daily_rf    = risk_free_rate / periods_per_year
    excess      = [r - daily_rf for r in returns]
    downside    = [min(r, 0.0) for r in excess]
    down_std    = _std(downside)
    if down_std == 0:
        return 0.0
    return (_mean(excess) / down_std) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: Sequence[float]) -> float:
    """Maximum drawdown as a positive fraction (0.15 = 15% drawdown)."""
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    mdd  = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        dd = (peak - value) / peak if peak > 0 else 0.0
        if dd > mdd:
            mdd = dd
    return round(mdd, 6)


def calmar_ratio(
    returns: Sequence[float],
    equity_curve: Sequence[float],
    periods_per_year: int = 252,
) -> float:
    """Calmar ratio = annualised return / max drawdown."""
    mdd = max_drawdown(equity_curve)
    if mdd == 0:
        return 0.0
    ann_return = _mean(returns) * periods_per_year
    return ann_return / mdd


def profit_factor(pnl_series: Sequence[float]) -> float:
    """Gross profit / gross loss.  Returns 0 if no losing trades."""
    gross_profit = sum(p for p in pnl_series if p > 0)
    gross_loss   = sum(abs(p) for p in pnl_series if p < 0)
    if gross_loss == 0:
        return 0.0
    return round(gross_profit / gross_loss, 4)


def win_rate(pnl_series: Sequence[float]) -> float:
    """Fraction of winning trades (0–1)."""
    if not pnl_series:
        return 0.0
    winners = sum(1 for p in pnl_series if p > 0)
    return round(winners / len(pnl_series), 4)


def avg_win_loss_ratio(pnl_series: Sequence[float]) -> float:
    """Average win / average loss (absolute values)."""
    wins   = [p for p in pnl_series if p > 0]
    losses = [abs(p) for p in pnl_series if p < 0]
    if not wins or not losses:
        return 0.0
    return round(_mean(wins) / _mean(losses), 4)


def compute_metrics(
    pnl_series: Sequence[float],
    equity_curve: Sequence[float] | None = None,
    risk_free_rate: float = 0.065,
    periods_per_year: int = 252,
) -> dict:
    """Compute the full set of risk/performance metrics in one call.

    Returns a dict safe to log, store, or display in the reporting UI.
    equity_curve defaults to a cumsum of pnl_series if not supplied.
    """
    if not pnl_series:
        return {"error": "no trades"}

    pnl  = list(pnl_series)
    total = sum(pnl)
    n     = len(pnl)

    if equity_curve is None:
        equity_curve = [sum(pnl[: i + 1]) for i in range(n)]

    returns_frac = [p / abs(equity_curve[i] or 1) for i, p in enumerate(pnl)]

    return {
        "total_trades":      n,
        "net_pnl":           round(total, 2),
        "win_rate":          win_rate(pnl),
        "profit_factor":     profit_factor(pnl),
        "avg_win_loss":      avg_win_loss_ratio(pnl),
        "sharpe":            round(sharpe_ratio(returns_frac, risk_free_rate, periods_per_year), 4),
        "sortino":           round(sortino_ratio(returns_frac, risk_free_rate, periods_per_year), 4),
        "max_drawdown_pct":  round(max_drawdown(list(equity_curve)) * 100, 4),
        "calmar":            round(calmar_ratio(returns_frac, list(equity_curve), periods_per_year), 4),
        "best_trade":        round(max(pnl), 2),
        "worst_trade":       round(min(pnl), 2),
        "avg_trade":         round(_mean(pnl), 2),
    }
