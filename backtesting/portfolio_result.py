"""PortfolioResult — Phase 5.

Stores the combined output of a PortfolioEngine run:
  - Daily equity curve across all positions
  - Per-symbol BacktestResult objects
  - Aggregate metrics: total return, max drawdown, Sharpe, Calmar
  - Monthly returns matrix

Usage:
    pr = PortfolioResult(
        equity_curve=pd.Series(..., index=dates),
        symbol_results={"RELIANCE.NS": result1, ...},
        trade_log=pd.DataFrame(...),
        initial_capital=1_000_000,
    )
    print(pr.summary())
    print(pr.monthly_returns())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from backtesting.result import BacktestResult


@dataclass
class PortfolioResult:
    """Complete result of a portfolio backtest run.

    Attributes:
        equity_curve    : Daily portfolio value as pd.Series (DatetimeIndex).
        symbol_results  : Per-symbol BacktestResult objects.
        trade_log       : DataFrame of all fills across all symbols.
        position_history: DataFrame of daily position counts/values.
        daily_pnl       : Day-over-day PnL Series.
        initial_capital : Starting capital.
        strategy_name   : Strategy used.
        period          : Period string e.g. '1y'.
    """

    equity_curve:     pd.Series                    = field(default_factory=pd.Series)
    symbol_results:   dict[str, BacktestResult]    = field(default_factory=dict)
    trade_log:        pd.DataFrame                 = field(default_factory=pd.DataFrame)
    position_history: pd.DataFrame                 = field(default_factory=pd.DataFrame)
    daily_pnl:        pd.Series                    = field(default_factory=pd.Series)
    initial_capital:  float                        = 100_000.0
    strategy_name:    str                          = ""
    period:           str                          = ""

    # ------------------------------------------------------------------
    # Core metrics (computed on demand)
    # ------------------------------------------------------------------

    @property
    def final_capital(self) -> float:
        return float(self.equity_curve.iloc[-1]) if len(self.equity_curve) > 0 else self.initial_capital

    @property
    def total_return_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return (self.final_capital - self.initial_capital) / self.initial_capital * 100

    @property
    def max_drawdown_pct(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        roll_max = self.equity_curve.cummax()
        drawdown = (self.equity_curve - roll_max) / roll_max
        return float(drawdown.min() * 100)  # negative value

    @property
    def sharpe_ratio(self) -> float:
        """Annualised Sharpe (daily returns, risk-free = 0)."""
        if len(self.equity_curve) < 2:
            return 0.0
        daily_ret = self.equity_curve.pct_change().dropna()
        if daily_ret.std() == 0:
            return 0.0
        return float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))

    @property
    def calmar_ratio(self) -> float:
        """CAGR divided by absolute max drawdown."""
        mdd = abs(self.max_drawdown_pct / 100)
        if mdd == 0:
            return 0.0
        return round(self.cagr / mdd, 4)

    @property
    def cagr(self) -> float:
        """Compound Annual Growth Rate (uses trading-day count)."""
        if len(self.equity_curve) < 2:
            return 0.0
        n_days    = len(self.equity_curve)
        n_years   = n_days / 252
        if n_years == 0 or self.initial_capital == 0:
            return 0.0
        return float((self.final_capital / self.initial_capital) ** (1 / n_years) - 1)

    @property
    def total_trades(self) -> int:
        if self.trade_log.empty:
            return 0
        return len(self.trade_log)

    # ------------------------------------------------------------------
    # Monthly returns
    # ------------------------------------------------------------------

    def monthly_returns(self) -> pd.DataFrame:
        """Pivot table of monthly returns (rows=year, cols=month).

        Values are percentage returns for that month.
        Returns empty DataFrame if equity_curve is empty or not DatetimeIndex.
        """
        if len(self.equity_curve) < 2:
            return pd.DataFrame()
        try:
            monthly = (
                self.equity_curve
                .resample("ME")
                .last()
                .pct_change()
                .dropna()
                * 100
            )
            df = monthly.to_frame(name="Return%")
            df.index = pd.DatetimeIndex(df.index)
            df["Year"]  = df.index.year
            df["Month"] = df.index.month
            pivot = df.pivot_table(
                values="Return%", index="Year", columns="Month"
            )
            pivot.columns = [
                ["Jan","Feb","Mar","Apr","May","Jun",
                 "Jul","Aug","Sep","Oct","Nov","Dec"][c - 1]
                for c in pivot.columns
            ]
            return pivot.round(2)
        except Exception:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Text summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        lines = [
            f"{'='*60}",
            f"  Portfolio Backtest: {self.strategy_name}  |  period={self.period}",
            f"{'='*60}",
            f"  Initial Capital  : ₹{self.initial_capital:>15,.0f}",
            f"  Final Capital    : ₹{self.final_capital:>15,.0f}",
            f"  Total Return     : {self.total_return_pct:>+.2f}%",
            f"  CAGR             : {self.cagr*100:>+.2f}%",
            f"  Max Drawdown     : {self.max_drawdown_pct:.2f}%",
            f"  Sharpe Ratio     : {self.sharpe_ratio:.4f}",
            f"  Calmar Ratio     : {self.calmar_ratio:.4f}",
            f"  Total Trades     : {self.total_trades}",
            f"  Symbols Active   : {len(self.symbol_results)}",
            f"{'='*60}",
        ]
        return "\n".join(lines)

    def to_equity_df(self) -> pd.DataFrame:
        return self.equity_curve.to_frame(name="portfolio_equity")

    def __repr__(self) -> str:
        return (
            f"<PortfolioResult return={self.total_return_pct:+.2f}% "
            f"sharpe={self.sharpe_ratio:.2f} mdd={self.max_drawdown_pct:.2f}%>"
        )
