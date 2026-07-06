"""Tests for BollingerRsi strategy.

Covers:
  - Registration in _STRATEGY_REGISTRY
  - generate_signals output shape, dtype, valid values
  - BUY signal on clear oversold + below-lower-band candle
  - SELL signal on clear overbought + above-upper-band candle
  - HOLD during warm-up period
  - validate_params accepts valid / rejects invalid
  - on_bar returns int in {-1, 0, 1}
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.base import _STRATEGY_REGISTRY
from strategies.bollinger_rsi import BollingerRsi


# ── fixtures ─────────────────────────────────────────────────────────────────


def _make_df(prices: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a list of close prices."""
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    close = pd.Series(prices, index=idx, dtype=float)
    return pd.DataFrame(
        {
            "Open":   close * 0.999,
            "High":   close * 1.005,
            "Low":    close * 0.995,
            "Close":  close,
            "Volume": 1_000_000,
        },
        index=idx,
    )


@pytest.fixture
def strategy() -> BollingerRsi:
    return BollingerRsi()


@pytest.fixture
def flat_df() -> pd.DataFrame:
    """100 bars of flat price — no signals expected."""
    return _make_df([100.0] * 100)


@pytest.fixture
def trending_df() -> pd.DataFrame:
    """60 bars trending up — supplies a meaningful range for indicator calc."""
    prices = [100 + i * 0.5 for i in range(60)]
    return _make_df(prices)


# ── registration ──────────────────────────────────────────────────────────────


def test_strategy_registered():
    assert "Bollinger RSI" in _STRATEGY_REGISTRY
    assert _STRATEGY_REGISTRY["Bollinger RSI"] is BollingerRsi


# ── basic contract ────────────────────────────────────────────────────────────


def test_generate_signals_shape(strategy, trending_df):
    sig = strategy.generate_signals(trending_df)
    assert isinstance(sig, pd.Series)
    assert len(sig) == len(trending_df)
    assert sig.dtype in (int, np.int64, np.int32)


def test_generate_signals_valid_values(strategy, trending_df):
    sig = strategy.generate_signals(trending_df)
    assert set(sig.unique()).issubset({-1, 0, 1})


def test_warmup_rows_are_hold(strategy):
    """The first `period - 1` bars must be HOLD (NaN warm-up)."""
    period = strategy.parameters["period"]  # 20
    df = _make_df([100.0] * 60)
    sig = strategy.generate_signals(df)
    assert (sig.iloc[: period - 1] == 0).all(), "warm-up rows must be HOLD"


# ── buy signal ────────────────────────────────────────────────────────────────


def test_buy_signal_triggered():
    """Force a BUY: final price well below lower band, with RSI in oversold.

    We build a series of 50 bars near 100, then crash the last bar to 70.
    This pushes close < lower band AND RSI < 30 (long down-run).
    """
    strat = BollingerRsi()
    # A steady decline triggers both conditions
    prices = [100 - i * 0.3 for i in range(49)] + [70.0]   # sharp final drop
    df  = _make_df(prices)
    sig = strat.generate_signals(df)
    # At least the last bar should fire BUY (or a recent bar during the crash)
    assert (sig == 1).any(), "Expected at least one BUY signal in falling series"


# ── sell signal ───────────────────────────────────────────────────────────────


def test_sell_signal_triggered():
    """Force a SELL: final price above upper band with RSI overbought."""
    strat = BollingerRsi()
    prices = [100 + i * 0.3 for i in range(49)] + [135.0]   # sharp final surge
    df  = _make_df(prices)
    sig = strat.generate_signals(df)
    assert (sig == -1).any(), "Expected at least one SELL signal in rising series"


# ── flat market → no extreme signals ─────────────────────────────────────────


def test_flat_market_no_extreme_signals(strategy, flat_df):
    """Flat price has zero standard deviation → bands collapse → no signals."""
    sig = strategy.generate_signals(flat_df)
    # With std=0, upper==lower==middle so no bar is strictly above/below
    assert (sig == 0).all() or set(sig.unique()).issubset({0})


# ── on_bar ────────────────────────────────────────────────────────────────────


def test_on_bar_returns_int(strategy, trending_df):
    result = strategy.on_bar(trending_df)
    assert isinstance(result, int)
    assert result in {-1, 0, 1}


def test_on_bar_insufficient_data(strategy):
    """Fewer bars than period → must return 0 (HOLD)."""
    df = _make_df([100.0] * 10)  # period is 20
    assert strategy.on_bar(df) == 0


# ── validate_params ───────────────────────────────────────────────────────────


def test_validate_params_valid(strategy):
    valid = {"period": 20, "std_dev": 2.0, "oversold": 30, "overbought": 70}
    assert strategy.validate_params(valid) is True


def test_validate_params_period_too_small(strategy):
    assert strategy.validate_params({"period": 3}) is False


def test_validate_params_std_dev_zero(strategy):
    assert strategy.validate_params({"std_dev": 0}) is False


def test_validate_params_oversold_above_50(strategy):
    assert strategy.validate_params({"oversold": 55}) is False


def test_validate_params_overbought_below_50(strategy):
    assert strategy.validate_params({"overbought": 45}) is False


# ── instance isolation (Phase 05 requirement) ─────────────────────────────────


def test_instance_isolation():
    """Tags and params must be independent per instance."""
    s1 = BollingerRsi()
    s2 = BollingerRsi()
    s1.tags.append("custom")
    s1.parameters["period"] = 50
    assert "custom" not in s2.tags
    assert s2.parameters["period"] == 20


# ── repr ──────────────────────────────────────────────────────────────────────


def test_repr(strategy):
    assert repr(strategy) == "Bollinger RSI v1.0.0"
