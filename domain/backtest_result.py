"""Eagle-Base BacktestResult Domain Model.

Full backtest run output with all metrics, trade log,
equity curve, and drawdown analysis.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
from pydantic import BaseModel, Field, computed_field

from domain.trade import Trade


class DrawdownPeriod(BaseModel):
    """A single drawdown episode."""
    model_config = {"frozen": True}
    start: datetime
    end: Optional[datetime] = None
    depth_pct: float
    duration_days: float = 0.0


class BacktestResult(BaseModel):
    """Complete backtest run result with full performance metrics."""

    model_config = {"frozen": False}

    result_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    strategy_name: str
    symbol: str
    exchange: str
    timeframe: str
    from_date: datetime
    to_date: datetime
    initial_capital: float = Field(..., gt=0)
    final_equity: float = Field(default=0.0)
    trade_log: List[Trade] = Field(default_factory=list)
    equity_curve: List[float] = Field(default_factory=list)
    equity_timestamps: List[datetime] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # --- Computed Metrics (populated by compute_metrics()) ---
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_commission: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_abs: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    cagr_pct: float = 0.0
    drawdown_periods: List[DrawdownPeriod] = Field(default_factory=list)

    def compute_metrics(self) -> None:
        """Compute all performance metrics from trade_log and equity_curve."""
        if not self.trade_log:
            return

        self.total_trades = len(self.trade_log)
        self.winning_trades = sum(1 for t in self.trade_log if t.is_winner)
        self.losing_trades = sum(1 for t in self.trade_log if t.is_loser)
        self.gross_profit = sum(t.net_pnl for t in self.trade_log if t.is_winner)
        self.gross_loss = abs(sum(t.net_pnl for t in self.trade_log if t.is_loser))
        self.total_commission = sum(t.commission for t in self.trade_log)
        self.final_equity = self.initial_capital + sum(t.net_pnl for t in self.trade_log)

        if self.equity_curve:
            self._compute_drawdown()
            self._compute_ratios()
            self._compute_cagr()

    def _compute_drawdown(self) -> None:
        curve = np.array(self.equity_curve, dtype=float)
        peak = np.maximum.accumulate(curve)
        drawdown = (curve - peak) / peak * 100
        self.max_drawdown_pct = float(abs(drawdown.min()))
        self.max_drawdown_abs = float(abs((curve - peak).min()))

        # Identify drawdown periods
        in_dd = False
        dd_start_idx = 0
        self.drawdown_periods = []
        for i, dd in enumerate(drawdown):
            if dd < 0 and not in_dd:
                in_dd = True
                dd_start_idx = i
            elif dd == 0 and in_dd:
                in_dd = False
                start_ts = (
                    self.equity_timestamps[dd_start_idx]
                    if self.equity_timestamps
                    else self.from_date
                )
                end_ts = (
                    self.equity_timestamps[i]
                    if self.equity_timestamps
                    else self.to_date
                )
                depth = float(abs(drawdown[dd_start_idx:i].min()))
                duration = (end_ts - start_ts).total_seconds() / 86400
                self.drawdown_periods.append(
                    DrawdownPeriod(
                        start=start_ts, end=end_ts, depth_pct=depth, duration_days=duration
                    )
                )

    def _compute_ratios(self) -> None:
        curve = np.array(self.equity_curve, dtype=float)
        returns = np.diff(curve) / curve[:-1]
        if len(returns) < 2:
            return
        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns, ddof=1))
        downside = returns[returns < 0]
        downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
        risk_free_daily = 0.065 / 252
        if std_ret > 0:
            self.sharpe_ratio = round(
                float((mean_ret - risk_free_daily) / std_ret * np.sqrt(252)), 3
            )
        if downside_std > 0:
            self.sortino_ratio = round(
                float((mean_ret - risk_free_daily) / downside_std * np.sqrt(252)), 3
            )
        if self.max_drawdown_pct > 0:
            self.calmar_ratio = round(self.cagr_pct / self.max_drawdown_pct, 3)

    def _compute_cagr(self) -> None:
        duration_years = (self.to_date - self.from_date).days / 365.25
        if duration_years <= 0 or self.initial_capital <= 0:
            return
        self.cagr_pct = round(
            ((self.final_equity / self.initial_capital) ** (1 / duration_years) - 1) * 100, 3
        )

    @property
    def net_pnl(self) -> float:
        return self.final_equity - self.initial_capital

    @property
    def total_return_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return round((self.net_pnl / self.initial_capital) * 100, 3)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return round((self.winning_trades / self.total_trades) * 100, 2)

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return round(self.gross_profit / self.gross_loss, 3)

    @property
    def avg_trade_pnl(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return round(self.net_pnl / self.total_trades, 2)

    def summary(self) -> Dict[str, Any]:
        """Return a flat summary dict suitable for display or export."""
        return {
            "strategy": self.strategy_name,
            "symbol": self.symbol,
            "from": str(self.from_date.date()),
            "to": str(self.to_date.date()),
            "initial_capital": self.initial_capital,
            "final_equity": round(self.final_equity, 2),
            "net_pnl": round(self.net_pnl, 2),
            "total_return_pct": self.total_return_pct,
            "cagr_pct": self.cagr_pct,
            "total_trades": self.total_trades,
            "win_rate_pct": self.win_rate,
            "profit_factor": self.profit_factor,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "avg_trade_pnl": self.avg_trade_pnl,
        }

    def __str__(self) -> str:
        return (
            f"BacktestResult[{self.strategy_name}|{self.symbol}] "
            f"Trades={self.total_trades} WinRate={self.win_rate:.1f}% "
            f"PnL={self.net_pnl:.2f} Sharpe={self.sharpe_ratio:.2f} "
            f"MaxDD={self.max_drawdown_pct:.2f}%"
        )
