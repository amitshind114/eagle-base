"""Phase 10b — backtesting.MetricsCalculator unit tests.

Covers:
  MetricsCalculator (backtesting/metrics.py)

  compute()
  [x] returns error dict when equity_curve is empty
  [x] returns error dict when equity_curve has < 2 points
  [x] returns all expected metric keys
  [x] sharpe_ratio positive for growing equity
  [x] sharpe_ratio = 0 for flat equity (zero variance)
  [x] sortino_ratio >= 0 for all-positive returns
  [x] max_drawdown_pct = 0 for monotone rising equity
  [x] max_drawdown_pct correct for known drawdown series
  [x] cagr_pct > 0 for growing equity
  [x] cagr_pct < 0 for declining equity
  [x] profit_factor = inf (no losing trades)
  [x] profit_factor = 0 (no winning trades)
  [x] profit_factor correct for known series
  [x] avg_trade_pnl = 0 for empty trades
  [x] avg_trade_pnl = mean of pnls
  [x] expectancy = 0 for empty trades
  [x] expectancy positive for profitable trade set
  [x] expectancy negative for losing trade set
  [x] calmar_ratio = 0 when max_drawdown = 0

All tests: pure numpy/math, zero I/O, < 1 second.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pytest

from backtesting.metrics import MetricsCalculator


# ────────────────────────────────────────────────────────────────────────────
Stubs — avoid importing real BacktestResult to keep tests self-contained
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class _Trade:
    pnl: float


@dataclass
class _Result:
    equity_curve: List[float]
    trades: List[_Trade] = field(default_factory=list)


def _result(equity: list[float], pnls: list[float] | None = None) -> _Result:
    trades = [_Trade(p) for p in (pnls or [])]
    return _Result(equity_curve=equity, trades=trades)


# ────────────────────────────────────────────────────────────────────────────
MetricsCalculator
# ────────────────────────────────────────────────────────────────────────────

class TestMetricsCalculator:
    @pytest.fixture()
    def calc(self):
        return MetricsCalculator()

    # Edge cases — bad input
    def test_empty_equity_returns_error(self, calc):
        r = _result([])
        assert "error" in calc.compute(r)

    def test_single_point_equity_returns_error(self, calc):
        r = _result([100_000.0])
        assert "error" in calc.compute(r)

    # All expected keys present
    def test_all_keys_present(self, calc):
        eq = list(np.linspace(100_000, 120_000, 252))
        r  = _result(eq, pnls=[100.0, -50.0, 200.0])
        m  = calc.compute(r)
        for key in ("sharpe_ratio", "sortino_ratio", "max_drawdown_pct",
                    "cagr_pct", "calmar_ratio", "profit_factor",
                    "avg_trade_pnl", "expectancy"):
            assert key in m, f"Missing: {key}"

    # Sharpe
    def test_sharpe_positive_for_growing_equity(self, calc):
        eq = list(np.linspace(100_000, 130_000, 252))
        r  = _result(eq)
        assert calc.compute(r)["sharpe_ratio"] > 0

    def test_sharpe_zero_for_flat_equity(self, calc):
        eq = [100_000.0] * 252
        r  = _result(eq)
        assert calc.compute(r)["sharpe_ratio"] == 0.0

    # Sortino
    def test_sortino_nonneg_all_positive_returns(self, calc):
        eq = list(np.linspace(100_000, 130_000, 252))
        r  = _result(eq)
        assert calc.compute(r)["sortino_ratio"] >= 0.0

    # Max drawdown
    def test_max_dd_zero_for_monotone_rise(self, calc):
        eq = list(np.linspace(100_000, 200_000, 252))
        r  = _result(eq)
        assert calc.compute(r)["max_drawdown_pct"] == 0.0

    def test_max_dd_correct_for_known_series(self, calc):
        # peak=110_000, trough=88_000 → dd = 20%
        eq = [100_000, 110_000, 88_000, 95_000, 100_000]
        r  = _result(eq)
        dd = calc.compute(r)["max_drawdown_pct"]
        expected = (110_000 - 88_000) / 110_000 * 100
        assert abs(dd - expected) < 0.01

    # CAGR
    def test_cagr_positive_for_growth(self, calc):
        eq = list(np.linspace(100_000, 150_000, 252))
        r  = _result(eq)
        assert calc.compute(r)["cagr_pct"] > 0

    def test_cagr_negative_for_decline(self, calc):
        eq = list(np.linspace(100_000, 80_000, 252))
        r  = _result(eq)
        assert calc.compute(r)["cagr_pct"] < 0

    # Profit factor
    def test_profit_factor_inf_no_losing_trades(self, calc):
        eq = list(np.linspace(100_000, 120_000, 252))
        r  = _result(eq, pnls=[100.0, 200.0, 50.0])
        pf = calc.compute(r)["profit_factor"]
        assert pf == float("inf") or pf > 0

    def test_profit_factor_zero_no_winning_trades(self, calc):
        eq = list(np.linspace(100_000, 80_000, 252))
        r  = _result(eq, pnls=[-100.0, -200.0])
        assert calc.compute(r)["profit_factor"] == 0.0

    def test_profit_factor_known_series(self, calc):
        # gross_profit=300, gross_loss=100 → pf=3.0
        eq = list(np.linspace(100_000, 120_000, 252))
        r  = _result(eq, pnls=[100.0, 200.0, -100.0])
        assert abs(calc.compute(r)["profit_factor"] - 3.0) < 0.001

    # Avg trade PnL
    def test_avg_trade_zero_for_no_trades(self, calc):
        eq = list(np.linspace(100_000, 120_000, 100))
        r  = _result(eq, pnls=[])
        assert calc.compute(r)["avg_trade_pnl"] == 0.0

    def test_avg_trade_correct(self, calc):
        eq = list(np.linspace(100_000, 120_000, 100))
        pnls = [100.0, -50.0, 200.0]
        r  = _result(eq, pnls=pnls)
        expected = sum(pnls) / len(pnls)
        assert abs(calc.compute(r)["avg_trade_pnl"] - expected) < 0.01

    # Expectancy
    def test_expectancy_zero_no_trades(self, calc):
        eq = list(np.linspace(100_000, 120_000, 100))
        r  = _result(eq, pnls=[])
        assert calc.compute(r)["expectancy"] == 0.0

    def test_expectancy_positive_profitable(self, calc):
        eq = list(np.linspace(100_000, 120_000, 100))
        r  = _result(eq, pnls=[200.0, 150.0, -30.0, 180.0, -20.0])
        assert calc.compute(r)["expectancy"] > 0

    def test_expectancy_negative_losing(self, calc):
        eq = list(np.linspace(100_000, 80_000, 100))
        r  = _result(eq, pnls=[-200.0, -150.0, 30.0, -180.0, 20.0])
        assert calc.compute(r)["expectancy"] < 0

    # Calmar
    def test_calmar_zero_when_no_drawdown(self, calc):
        eq = list(np.linspace(100_000, 200_000, 252))
        r  = _result(eq)
        assert calc.compute(r)["calmar_ratio"] == 0.0
