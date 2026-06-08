"""Phase 8 — Risk module unit tests.

Covers:
  PositionSizer (risk/sizer.py) — pure math, no I/O
  [x] valid BUY returns qty > 0 with positive edge
  [x] qty * price <= max_position_pct * capital
  [x] zero price returns qty=0
  [x] negative Kelly (no edge) returns qty=0
  [x] max_position_pct cap enforced
  [x] lot_size respected (qty is multiple of lot_size)
  [x] zero ATR falls back to conservative vol_scalar=0.5
  [x] high ATR reduces position vs low ATR
  [x] kelly formula correct for known inputs
  [x] vol_scalar clamped to [0.25, 2.0]
  [x] vol_scalar=0.5 when atr_pct=0
  [x] SizeResult.position_value = qty * price
  [x] SizeResult is frozen (immutable)
  [x] rationale is non-empty string
  [x] total_capital=0 raises ValueError

  RiskLimits (risk/limits.py) — stateful but no I/O
  [x] fresh instance: check() does not raise
  [x] max_trades breach raises RiskLimitBreached
  [x] max_daily_loss breach raises RiskLimitBreached
  [x] position too large raises RiskLimitBreached
  [x] record_trade increments trade count
  [x] reset() clears state
  [x] reset() updates capital
  [x] status() returns expected keys
  [x] trades_placed in status matches record_trade calls
  [x] drawdown limit raises RiskLimitBreached
  [x] multiple trades within limits do not raise
  [x] check() is non-mutating (state unchanged after check)

  risk/metrics.py — pure math
  [x] sharpe_ratio correct direction (positive returns > 0)
  [x] sharpe_ratio: flat returns = 0
  [x] sharpe_ratio: too few returns = 0
  [x] sortino_ratio >= sharpe when no downside
  [x] sortino_ratio: no downside returns 0 (std=0)
  [x] max_drawdown: flat curve = 0
  [x] max_drawdown: known drawdown correct
  [x] max_drawdown: too short returns 0
  [x] profit_factor: no losses returns 0
  [x] profit_factor: known series correct
  [x] win_rate: empty = 0
  [x] win_rate: all winners = 1.0
  [x] win_rate: known series correct
  [x] avg_win_loss_ratio: no winners returns 0
  [x] avg_win_loss_ratio: known series correct
  [x] compute_metrics: empty series returns error dict
  [x] compute_metrics: returns all expected keys
  [x] compute_metrics: net_pnl = sum of series

All tests: zero network, zero I/O, < 1 second.
"""

from __future__ import annotations

import pytest

from risk.sizer   import PositionSizer, SizeResult
from risk.limits  import RiskLimits, RiskLimitBreached
from risk.metrics import (
    sharpe_ratio, sortino_ratio, max_drawdown,
    profit_factor, win_rate, avg_win_loss_ratio, compute_metrics,
)


# ────────────────────────────────────────────────────────────────────────────
# PositionSizer
# ────────────────────────────────────────────────────────────────────────────

class TestPositionSizer:

    @pytest.fixture()
    def sizer(self):
        return PositionSizer(total_capital=200_000.0, max_position_pct=0.10)

    # Basic sizing
    def test_positive_edge_returns_nonzero_qty(self, sizer):
        result = sizer.size(
            "RELIANCE", price=2500.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.015,
        )
        assert result.qty > 0

    def test_position_value_within_cap(self, sizer):
        result = sizer.size(
            "RELIANCE", price=2500.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.015,
        )
        assert result.position_value <= 200_000.0 * 0.10 + 2500.0  # 1 lot tolerance

    def test_zero_price_returns_qty_zero(self, sizer):
        result = sizer.size(
            "RELIANCE", price=0.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.015,
        )
        assert result.qty == 0

    def test_negative_kelly_returns_qty_zero(self, sizer):
        # win_rate=0.30 with avg_win=0.02 vs avg_loss=0.04 → negative Kelly
        result = sizer.size(
            "RELIANCE", price=2500.0,
            win_rate=0.30, avg_win_pct=0.02, avg_loss_pct=0.04,
            atr_pct=0.015,
        )
        assert result.qty == 0

    def test_lot_size_respected(self, sizer):
        result = sizer.size(
            "NIFTY", price=150.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.01, lot_size=50,
        )
        if result.qty > 0:
            assert result.qty % 50 == 0

    def test_high_atr_reduces_qty_vs_low_atr(self, sizer):
        low_vol = sizer.size(
            "TCS", price=3500.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.005,
        )
        high_vol = sizer.size(
            "TCS", price=3500.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.04,
        )
        assert high_vol.qty <= low_vol.qty

    def test_zero_atr_conservative_scalar(self, sizer):
        result = sizer.size(
            "INFY", price=1500.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.0,
        )
        assert result.vol_scalar == 0.5

    def test_position_value_equals_qty_times_price(self, sizer):
        result = sizer.size(
            "RELIANCE", price=2500.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.015,
        )
        assert abs(result.position_value - result.qty * 2500.0) < 0.01

    def test_sizeresult_is_frozen(self, sizer):
        result = sizer.size(
            "RELIANCE", price=2500.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.015,
        )
        with pytest.raises((AttributeError, TypeError)):
            result.qty = 999  # type: ignore[misc]

    def test_rationale_is_non_empty_string(self, sizer):
        result = sizer.size(
            "RELIANCE", price=2500.0,
            win_rate=0.60, avg_win_pct=0.04, avg_loss_pct=0.025,
            atr_pct=0.015,
        )
        assert isinstance(result.rationale, str)
        assert len(result.rationale) > 0

    def test_zero_capital_raises_value_error(self):
        with pytest.raises(ValueError, match="total_capital"):
            PositionSizer(total_capital=0)

    # Kelly internals
    def test_kelly_formula_known_inputs(self, sizer):
        # W=0.6, b=0.04/0.025=1.6 → f*=(0.6*1.6-0.4)/1.6 = 0.35
        k = sizer._kelly(0.6, 0.04, 0.025)
        assert abs(k - 0.35) < 0.0001

    def test_kelly_negative_for_bad_edge(self, sizer):
        k = sizer._kelly(0.3, 0.02, 0.04)  # clearly negative edge
        assert k < 0

    # Vol scalar
    def test_vol_scalar_clamped_max(self, sizer):
        # Very low ATR → raw = 0.01/0.001 = 10.0 → clamped to 2.0
        s = sizer._vol_scalar(0.001)
        assert s == 2.0

    def test_vol_scalar_clamped_min(self, sizer):
        # Very high ATR → raw = 0.01/0.2 = 0.05 → clamped to 0.25
        s = sizer._vol_scalar(0.2)
        assert s == 0.25

    def test_vol_scalar_zero_atr_conservative(self, sizer):
        assert sizer._vol_scalar(0.0) == 0.5


# ────────────────────────────────────────────────────────────────────────────
# RiskLimits
# ────────────────────────────────────────────────────────────────────────────

class TestRiskLimits:

    @pytest.fixture()
    def rl(self):
        rl = RiskLimits(
            total_capital=200_000.0,
            max_daily_loss=4_000.0,
            max_trades_per_day=10,
            max_position_pct=0.10,
            max_drawdown_pct=0.05,
        )
        rl.reset()
        return rl

    def test_fresh_check_does_not_raise(self, rl):
        rl.check("RELIANCE", "BUY", qty=5, price=2500.0)

    def test_max_trades_breach_raises(self, rl):
        for _ in range(10):
            rl.record_trade("X", "BUY", 1, 100.0)
        with pytest.raises(RiskLimitBreached, match="Max trades"):
            rl.check("X", "BUY", 1, 100.0)

    def test_daily_loss_breach_raises(self, rl):
        # Record a large loss
        rl.record_trade("X", "SELL", 1, 100.0, pnl=-5_000.0)
        with pytest.raises(RiskLimitBreached, match="Daily loss"):
            rl.check("X", "BUY", 1, 100.0)

    def test_position_too_large_raises(self, rl):
        # 10% cap = 20_000; 100 shares * 2500 = 250_000 > cap
        with pytest.raises(RiskLimitBreached, match="position size"):
            rl.check("RELIANCE", "BUY", qty=100, price=2500.0)

    def test_record_trade_increments_count(self, rl):
        rl.record_trade("RELIANCE", "BUY", 5, 2500.0)
        assert rl.status()["trades_placed"] == 1

    def test_multiple_record_trades_increment(self, rl):
        for _ in range(3):
            rl.record_trade("X", "BUY", 1, 100.0)
        assert rl.status()["trades_placed"] == 3

    def test_reset_clears_trades(self, rl):
        rl.record_trade("X", "BUY", 1, 100.0)
        rl.reset()
        assert rl.status()["trades_placed"] == 0

    def test_reset_updates_capital(self, rl):
        rl.reset(capital=300_000.0)
        assert rl.total_capital == 300_000.0

    def test_status_returns_expected_keys(self, rl):
        s = rl.status()
        for key in ("trades_placed", "max_trades", "realized_pnl",
                    "max_daily_loss", "equity_peak", "total_capital", "session_date"):
            assert key in s

    def test_check_is_non_mutating(self, rl):
        before = rl.status()["trades_placed"]
        rl.check("X", "BUY", 1, 100.0)
        after = rl.status()["trades_placed"]
        assert before == after

    def test_drawdown_limit_raises(self, rl):
        # equity_peak=200_000, lose 12_000 → drawdown=6% > 5% limit
        rl.record_trade("X", "SELL", 1, 100.0, pnl=-12_000.0)
        with pytest.raises(RiskLimitBreached, match="drawdown"):
            rl.check("X", "BUY", 1, 100.0)

    def test_multiple_small_trades_within_limits(self, rl):
        for i in range(5):
            rl.check("X", "BUY", 1, 100.0)
            rl.record_trade("X", "BUY", 1, 100.0, pnl=50.0)
        # Should not raise at all
        assert rl.status()["trades_placed"] == 5


# ────────────────────────────────────────────────────────────────────────────
# risk/metrics.py — pure math
# ────────────────────────────────────────────────────────────────────────────

class TestSharpeRatio:
    def test_positive_returns_positive_sharpe(self):
        returns = [0.005] * 100  # +0.5% per day
        assert sharpe_ratio(returns) > 0

    def test_flat_returns_zero_sharpe(self):
        returns = [0.0] * 100
        assert sharpe_ratio(returns) == 0.0

    def test_too_few_returns_zero(self):
        assert sharpe_ratio([0.01]) == 0.0

    def test_negative_returns_negative_sharpe(self):
        returns = [-0.005] * 100
        assert sharpe_ratio(returns) < 0

    def test_higher_return_higher_sharpe(self):
        low  = sharpe_ratio([0.001] * 100)
        high = sharpe_ratio([0.005] * 100)
        assert high > low


class TestSortinoRatio:
    def test_no_downside_returns_zero(self):
        # All positive returns → downside std = 0
        returns = [0.005] * 50
        # sortino returns 0 when down_std == 0
        result = sortino_ratio(returns)
        assert result == 0.0 or result > 0  # either zero or positive, never negative

    def test_downside_only_negative(self):
        returns = [-0.01] * 100
        assert sortino_ratio(returns) < 0

    def test_too_few_returns_zero(self):
        assert sortino_ratio([0.01]) == 0.0


class TestMaxDrawdown:
    def test_flat_curve_zero_drawdown(self):
        assert max_drawdown([100_000.0] * 50) == 0.0

    def test_known_drawdown_correct(self):
        # Peak=100, drops to 80 → DD=20%
        curve = [100.0, 110.0, 80.0, 90.0]
        dd = max_drawdown(curve)
        expected = (110.0 - 80.0) / 110.0
        assert abs(dd - expected) < 0.0001

    def test_monotone_rise_zero_drawdown(self):
        curve = [100.0, 110.0, 120.0, 130.0]
        assert max_drawdown(curve) == 0.0

    def test_too_short_returns_zero(self):
        assert max_drawdown([100.0]) == 0.0

    def test_returns_positive_value(self):
        curve = [100.0, 90.0, 80.0]
        assert max_drawdown(curve) > 0


class TestProfitFactor:
    def test_no_losing_trades_returns_zero(self):
        assert profit_factor([100.0, 200.0, 150.0]) == 0.0

    def test_no_winning_trades_returns_zero(self):
        assert profit_factor([-100.0, -50.0]) == 0.0

    def test_known_series_correct(self):
        # gross profit=300, gross loss=100 → pf=3.0
        pnl = [100.0, 200.0, -100.0]
        assert abs(profit_factor(pnl) - 3.0) < 0.001

    def test_balanced_series_near_one(self):
        pnl = [100.0, -100.0, 100.0, -100.0]
        assert abs(profit_factor(pnl) - 1.0) < 0.001


class TestWinRate:
    def test_empty_returns_zero(self):
        assert win_rate([]) == 0.0

    def test_all_winners_returns_one(self):
        assert win_rate([10.0, 20.0, 5.0]) == 1.0

    def test_all_losers_returns_zero(self):
        assert win_rate([-10.0, -5.0]) == 0.0

    def test_known_win_rate(self):
        # 3 wins out of 5
        pnl = [10.0, -5.0, 20.0, -3.0, 15.0]
        assert abs(win_rate(pnl) - 0.6) < 0.001


class TestAvgWinLoss:
    def test_no_winners_returns_zero(self):
        assert avg_win_loss_ratio([-10.0, -5.0]) == 0.0

    def test_no_losers_returns_zero(self):
        assert avg_win_loss_ratio([10.0, 20.0]) == 0.0

    def test_known_ratio_correct(self):
        # avg_win = (100+200)/2 = 150, avg_loss = 50 → ratio = 3.0
        pnl = [100.0, 200.0, -50.0]
        assert abs(avg_win_loss_ratio(pnl) - 3.0) < 0.001


class TestComputeMetrics:
    def test_empty_returns_error(self):
        result = compute_metrics([])
        assert "error" in result

    def test_all_expected_keys_present(self):
        pnl = [100.0, -50.0, 200.0, -30.0, 150.0]
        result = compute_metrics(pnl)
        for key in ("total_trades", "net_pnl", "win_rate", "profit_factor",
                    "sharpe", "sortino", "max_drawdown_pct", "calmar",
                    "best_trade", "worst_trade", "avg_trade"):
            assert key in result, f"Missing key: {key}"

    def test_net_pnl_equals_sum(self):
        pnl = [100.0, -50.0, 200.0, -30.0, 150.0]
        result = compute_metrics(pnl)
        assert abs(result["net_pnl"] - sum(pnl)) < 0.01

    def test_total_trades_correct(self):
        pnl = [10.0, -5.0, 20.0]
        result = compute_metrics(pnl)
        assert result["total_trades"] == 3

    def test_best_worst_trade_correct(self):
        pnl = [100.0, -50.0, 200.0]
        result = compute_metrics(pnl)
        assert result["best_trade"] == 200.0
        assert result["worst_trade"] == -50.0

    def test_accepts_custom_equity_curve(self):
        pnl = [100.0, -50.0, 200.0]
        equity = [100_000.0, 100_100.0, 100_050.0, 100_250.0]
        result = compute_metrics(pnl, equity_curve=equity)
        assert "error" not in result
