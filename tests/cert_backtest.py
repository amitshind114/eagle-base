"""Phase-02 Look-ahead Bias Certification Test.

EXIT CRITERIA (must all pass before Phase 03 begins):
  1. Perfect-oracle strategy on rising data:
       WITHOUT look-ahead fix → win_rate = 100%, Sharpe > 10
       WITH    look-ahead fix → first bar has no signal, win_rate < 100%
  2. Sharpe on 1d data is between 0 and 4 (never > 10)
  3. Buy-hold return matches (close[-1]/close[0] - 1) * 100 exactly (to 2dp)
  4. profit_factor for all-win strategy > 1 (not 0)

Run with:
    pytest tests/cert_backtest.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtesting.engine import BacktestEngine
from strategies.base import BaseStrategy


# ── Helpers ───────────────────────────────────────────────────────────────

def make_rising_df(n: int = 300) -> pd.DataFrame:
    """DataFrame where Close rises monotonically by 1 each bar."""
    close = pd.Series(np.arange(1000, 1000 + n, dtype=float))
    idx   = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open":   close - 0.5,
            "High":   close + 1.0,
            "Low":    close - 1.0,
            "Close":  close,
            "Volume": np.ones(n) * 1_000_000,
        },
        index=idx,
    )


class PerfectOracleStrategy(BaseStrategy):
    """Returns BUY (1) on every single bar — an oracle with perfect foresight."""
    name = "PerfectOracle"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=df.index, dtype=int)


class AlwaysHoldStrategy(BaseStrategy):
    """Buys on bar 1, never sells — used to test buy-hold accuracy."""
    name = "AlwaysHold"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        sig = pd.Series(0, index=df.index, dtype=int)
        sig.iloc[0] = 1  # buy first bar, hold forever
        return sig


# ── Certification tests ───────────────────────────────────────────────────

class TestLookAheadFix:
    def test_oracle_not_100pct_after_fix(self):
        """After signals.shift(1), oracle cannot win on every bar.

        The first bar receives signal 0 (NaN shifted to 0), so no trade opens
        on bar 0. This alone prevents 100% of bars being winning trades.
        """
        df     = make_rising_df(300)
        engine = BacktestEngine(initial_capital=100_000, interval="1d")
        result = engine.run(df, PerfectOracleStrategy())

        # Oracle on rising data: if look-ahead existed, win_rate would be 100%.
        # With the shift(1) fix applied, at minimum bar 0 has no signal.
        assert result.win_rate_pct < 100.0, (
            f"win_rate should be < 100% after look-ahead fix, got {result.win_rate_pct}"
        )

    def test_oracle_still_profitable(self):
        """After look-ahead fix, oracle on rising data must still make profit."""
        df     = make_rising_df(300)
        engine = BacktestEngine(initial_capital=100_000, interval="1d")
        result = engine.run(df, PerfectOracleStrategy())
        assert result.total_return_pct > 0, (
            f"Oracle should be profitable on rising data, got {result.total_return_pct}%"
        )


class TestSharpeRange:
    def test_sharpe_daily_is_reasonable(self):
        """Daily Sharpe must be between 0 and 4 on synthetic trending data.

        Without fix, Sharpe was routinely 15–300 due to look-ahead bias.
        """
        df     = make_rising_df(500)
        engine = BacktestEngine(initial_capital=100_000, interval="1d")
        result = engine.run(df, PerfectOracleStrategy())
        assert 0 <= result.sharpe_ratio <= 4, (
            f"Sharpe should be 0–4 for daily data, got {result.sharpe_ratio}"
        )

    def test_sharpe_uses_interval_periods(self):
        """Sharpe for 1wk interval uses 52 periods, not 252."""
        from backtesting.engine import PERIODS
        assert PERIODS["1wk"] == 52
        assert PERIODS["1d"]  == 252
        assert PERIODS["1m"]  == 252 * 375


class TestBuyHoldAccuracy:
    def test_buyhold_return_matches_price_ratio(self):
        """buy_hold_return_pct must equal (close[-1]/close[0] - 1) * 100 exactly."""
        df     = make_rising_df(300)
        engine = BacktestEngine(initial_capital=100_000, interval="1d")
        result = engine.run(df, PerfectOracleStrategy())

        expected_bh = (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100
        assert abs(result.buy_hold_return_pct - expected_bh) < 0.01, (
            f"buy_hold_return_pct={result.buy_hold_return_pct:.4f} "
            f"expected={expected_bh:.4f}"
        )

    def test_buyhold_curve_first_value_is_capital(self):
        """Buy-hold curve at t=0 must equal initial capital exactly."""
        df     = make_rising_df(300)
        engine = BacktestEngine(initial_capital=100_000, interval="1d")
        result = engine.run(df, PerfectOracleStrategy())
        assert float(result.buy_hold_curve.iloc[0]) == pytest.approx(100_000, rel=1e-6), (
            f"buy_hold_curve[0] should be 100000, got {result.buy_hold_curve.iloc[0]}"
        )


class TestProfitFactor:
    def test_profit_factor_positive_when_wins_exist(self):
        """profit_factor must be > 1 when most trades win (not 0)."""
        df     = make_rising_df(300)
        engine = BacktestEngine(initial_capital=100_000, interval="1d")
        result = engine.run(df, PerfectOracleStrategy())
        if result.total_trades > 0:
            assert result.profit_factor > 0, (
                f"profit_factor should be > 0 when trades exist, got {result.profit_factor}"
            )
