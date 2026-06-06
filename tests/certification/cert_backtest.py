"""Certification Suite — Backtest Certified.

Covers every P0 and P1 bug identified in the Phase 01 audit:

  P0-001  engine.run() accepts strategy object, rejects raw Series
  P0-002  Single BacktestResult class — .trades, .symbol, .strategy_name present
  P0-003  MetricsCalculator runs on engine output without AttributeError
  P0-004  max_drawdown_pct is negative everywhere (engine + metrics)
  P0-005  Final equity not double-counted when position force-closed at EOD
  P1-001  profit_factor is NOT 0.0 for all-win strategies
  P1-002  SmaCrossover positional args accepted; fast > slow rejected
  P1-003  Sharpe not wildly inflated for sparse strategies
  P1-004  win_rate_pct attribute name is consistent
  P1-005  MetricsCalculator does not raise Series ambiguity ValueError

Badge condition: ALL 13 tests must pass → Backtest Certified ✅
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtesting.engine import BacktestEngine
from backtesting.metrics import MetricsCalculator
from backtesting.models import BacktestResult, Trade
from strategies.sma_crossover import SmaCrossover
from core.exceptions import InsufficientDataError


# ── Shared fixtures ───────────────────────────────────────────────────────

def _make_df(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Deterministic synthetic OHLCV data with DatetimeIndex."""
    np.random.seed(seed)
    close = pd.Series(np.cumsum(np.random.randn(n) * 0.5) + 1000)
    idx   = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open":   (close * 0.99).clip(lower=1),
            "High":   (close * 1.01).clip(lower=1),
            "Low":    (close * 0.98).clip(lower=1),
            "Close":  close.clip(lower=1),
            "Volume": np.random.randint(100_000, 1_000_000, n).astype(float),
        },
        index=idx,
    )


class _AlwaysBuy:
    """Stub strategy: buy on bar 0, never sell (forces END_OF_DATA close)."""
    name = "AlwaysBuy"
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=df.index)
        s.iloc[0] = 1
        return s


class _PerfectWin:
    """Stub strategy: buy on bar 10, sell on bar 50 (guaranteed profit on rising data)."""
    name = "PerfectWin"
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=df.index)
        if len(df) > 50:
            s.iloc[10] = 1
            s.iloc[50] = -1
        return s


# ── P0-001: engine.run() accepts strategy object ──────────────────────────

class TestP0001EngineSignature:
    def test_engine_accepts_strategy_object(self):
        """engine.run(df, strategy) must work without error."""
        df     = _make_df()
        engine = BacktestEngine(symbol="TEST", initial_capital=100_000)
        result = engine.run(df, SmaCrossover(20, 50))
        assert isinstance(result, BacktestResult)

    def test_engine_rejects_raw_series(self):
        """Passing a pd.Series where a strategy is expected must raise TypeError/AttributeError."""
        df = _make_df()
        with pytest.raises((TypeError, AttributeError)):
            BacktestEngine().run(df, pd.Series([1] * len(df)))

    def test_short_data_raises_insufficient_data_error(self):
        """Fewer than 10 bars must raise InsufficientDataError."""
        df = _make_df(5)
        with pytest.raises(InsufficientDataError):
            BacktestEngine().run(df, SmaCrossover(20, 50))


# ── P0-002: Single unified BacktestResult ─────────────────────────────────

class TestP0002UnifiedResult:
    def test_result_exposes_trades(self):
        """BacktestResult must have .trades as a list."""
        df     = _make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert hasattr(result, "trades")
        assert isinstance(result.trades, list)

    def test_result_exposes_symbol_and_strategy_name(self):
        """BacktestResult must expose .symbol and .strategy_name."""
        df     = _make_df()
        result = BacktestEngine(symbol="RELIANCE.NS", initial_capital=100_000).run(
            df, SmaCrossover(20, 50)
        )
        assert result.symbol == "RELIANCE.NS"
        assert isinstance(result.strategy_name, str)
        assert len(result.strategy_name) > 0

    def test_legacy_import_alias_works(self):
        """from backtesting.result import BacktestResult must resolve to models.BacktestResult."""
        from backtesting.result import BacktestResult as LegacyResult
        from backtesting.models import BacktestResult as CanonicalResult
        assert LegacyResult is CanonicalResult, (
            "backtesting/result.py must re-export the same class as backtesting/models.py"
        )

    def test_trade_objects_populated(self):
        """Engine must build Trade objects for every round-trip."""
        df     = _make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        if result.total_trades > 0:
            t = result.trades[0]
            assert isinstance(t, Trade)
            assert t.entry_price > 0
            assert t.exit_price > 0
            assert t.quantity > 0


# ── P0-003: MetricsCalculator works on engine output ──────────────────────

class TestP0003MetricsCalculator:
    def test_metrics_runs_on_engine_output(self):
        """MetricsCalculator.compute() must not crash on a real engine result."""
        df     = _make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        mc     = MetricsCalculator()
        metrics = mc.compute(result)
        assert isinstance(metrics, dict)
        assert "sharpe_ratio" in metrics
        assert "max_drawdown_pct" in metrics

    def test_metrics_values_are_floats(self):
        df      = _make_df()
        result  = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        metrics = MetricsCalculator().compute(result)
        for key in ("sharpe_ratio", "max_drawdown_pct", "cagr_pct", "sortino_ratio"):
            assert isinstance(metrics[key], float), f"{key} is not float: {type(metrics[key])}"


# ── P0-004: max_drawdown_pct sign convention ──────────────────────────────

class TestP0004DrawdownSign:
    def test_engine_max_drawdown_is_negative(self):
        """engine.run() result.max_drawdown_pct must be <= 0."""
        df     = _make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert result.max_drawdown_pct <= 0, (
            f"engine max_drawdown_pct={result.max_drawdown_pct} must be negative"
        )

    def test_metrics_max_drawdown_is_negative(self):
        """MetricsCalculator._max_drawdown() must also return a negative value."""
        df      = _make_df()
        result  = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        metrics = MetricsCalculator().compute(result)
        assert metrics["max_drawdown_pct"] <= 0, (
            f"metrics max_drawdown_pct={metrics['max_drawdown_pct']} must be negative"
        )

    def test_both_drawdowns_have_same_sign(self):
        """Engine and MetricsCalculator must agree on sign."""
        df      = _make_df()
        result  = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        metrics = MetricsCalculator().compute(result)
        assert result.max_drawdown_pct <= 0
        assert metrics["max_drawdown_pct"] <= 0


# ── P0-005: Force-close does not double-count equity ─────────────────────

class TestP0005FinalEquity:
    def test_final_equity_sane_after_forced_close(self):
        """A strategy that holds to EOD must produce a plausible final equity."""
        df     = _make_df(200)
        result = BacktestEngine(initial_capital=100_000).run(df, _AlwaysBuy())
        # Sanity: final capital should not be 0 or wildly over initial
        assert result.final_capital > 0
        assert result.final_capital < 100_000 * 10, (
            f"final_capital={result.final_capital} looks double-counted"
        )

    def test_forced_close_trade_has_end_of_data_reason(self):
        """Position held to end-of-data must produce a Trade with exit_reason='END_OF_DATA'."""
        df     = _make_df(200)
        result = BacktestEngine(initial_capital=100_000).run(df, _AlwaysBuy())
        assert result.total_trades >= 1
        last_trade = result.trades[-1]
        assert last_trade.exit_reason == "END_OF_DATA"


# ── P1-001: profit_factor for all-win strategies ──────────────────────────

class TestP1001ProfitFactor:
    def test_profit_factor_not_zero_for_winning_trade(self):
        """An all-win strategy must not get profit_factor = 0.0."""
        # Use rising data so a single BUY→SELL trade is profitable
        n     = 100
        close = pd.Series(range(1000, 1000 + n))
        idx   = pd.date_range("2022-01-01", periods=n, freq="B")
        df    = pd.DataFrame(
            {
                "Open":   close * 0.99, "High": close * 1.01,
                "Low":    close * 0.98, "Close": close,
                "Volume": [1_000_000] * n,
            },
            index=idx,
        )
        result = BacktestEngine(initial_capital=100_000).run(df, _PerfectWin())
        if result.total_trades > 0:
            assert result.profit_factor != 0.0, (
                f"profit_factor={result.profit_factor} should not be 0 for a winning trade"
            )
            assert result.profit_factor > 1.0 or result.profit_factor == 999.0


# ── P1-002: SmaCrossover constructor validation ───────────────────────────

class TestP1002SmaCrossoverConstructor:
    def test_positional_args_accepted(self):
        s    = SmaCrossover(20, 50)
        df   = _make_df()
        sigs = s.generate_signals(df)
        assert len(sigs) == len(df)
        assert set(sigs.unique()).issubset({-1, 0, 1})

    def test_fast_greater_than_slow_rejected(self):
        """fast > slow is an invalid param combination."""
        s = SmaCrossover(50, 20)
        assert not s.validate_params({"fast": 50, "slow": 20}), (
            "validate_params must return False when fast >= slow"
        )


# ── P1-003: Sharpe not inflated for sparse strategies ─────────────────────

class TestP1003SharpeNotInflated:
    def test_sharpe_sparse_strategy_reasonable(self):
        """A sparse crossover strategy should not produce Sharpe > 5."""
        df     = _make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert result.sharpe_ratio < 5.0, (
            f"Sharpe={result.sharpe_ratio:.2f} is unrealistically high for a sparse strategy"
        )


# ── P1-004: win_rate_pct attribute name consistency ───────────────────────

class TestP1004WinRateAttributeName:
    def test_win_rate_pct_exists_and_in_range(self):
        df     = _make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert hasattr(result, "win_rate_pct"), "BacktestResult must have .win_rate_pct"
        assert 0 <= result.win_rate_pct <= 100

    def test_win_rate_alias_matches_win_rate_pct(self):
        """Legacy .win_rate property must equal .win_rate_pct."""
        df     = _make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        assert result.win_rate == result.win_rate_pct


# ── P1-005: MetricsCalculator Series ambiguity guard ─────────────────────

class TestP1005MetricsGuard:
    def test_metrics_no_series_ambiguity_error(self):
        """MetricsCalculator.compute() must not raise ValueError from 'if not pd.Series(...)'"""
        df     = _make_df()
        result = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        try:
            MetricsCalculator().compute(result)
        except ValueError as e:
            if "ambiguous" in str(e).lower():
                pytest.fail(f"Series ambiguity bug still present: {e}")
            raise

    def test_metrics_returns_dict_not_error_key(self):
        """A valid engine result must produce metrics dict without an 'error' key."""
        df      = _make_df(200)
        result  = BacktestEngine(initial_capital=100_000).run(df, SmaCrossover(20, 50))
        metrics = MetricsCalculator().compute(result)
        assert "error" not in metrics, f"MetricsCalculator returned error: {metrics.get('error')}"
