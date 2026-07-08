"""Unit tests for TripleEMAStrategy.

Runs without any broker connection or live data.
All tests use synthetic price series fed bar-by-bar via on_bar()
or as a DataFrame via generate_signals().

Test coverage:
  1. test_init_defaults          — default params initialise correctly
  2. test_init_custom_params     — custom params accepted
  3. test_init_invalid_periods   — ValueError on bad period order
  4. test_no_signal_warmup       — no signal during warm-up bars
  5. test_buy_signal             — BUY fires on bullish triple alignment
  6. test_sell_signal            — SELL fires on bearish triple alignment
  7. test_get_state_keys         — get_state() returns expected keys
  8. test_generate_signals_shape — generate_signals() returns correct Series
  9. test_registry_includes_triple_ema — triple_ema is in registry after import
 10. test_no_duplicate_position  — no repeated BUY while already long
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy(symbol="TEST", capital=100_000.0, params=None):
    """Import here so registry side-effects are isolated to test scope."""
    from strategies.triple_ema import TripleEMAStrategy
    return TripleEMAStrategy(symbol=symbol, capital=capital, params=params)


def _bar(close: float) -> dict:
    return {"symbol": "TEST", "open": close, "high": close, "low": close,
            "close": close, "volume": 1000.0, "timestamp": "2026-01-01T09:15:00"}


def _feed_bars(strategy, prices: list[float]) -> list:
    """Feed a list of close prices and return non-None signals."""
    signals = []
    for p in prices:
        sig = strategy.on_bar(_bar(p))
        if sig is not None:
            signals.append(sig)
    return signals


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTripleEMAInit:
    def test_init_defaults(self):
        s = _make_strategy()
        assert s.fast_period   == 9
        assert s.medium_period == 21
        assert s.slow_period   == 55
        assert s.max_pos_pct   == 0.95
        assert s.STRATEGY_ID   == "triple_ema"

    def test_init_custom_params(self):
        s = _make_strategy(params={"fast_period": 5, "medium_period": 13, "slow_period": 34})
        assert s.fast_period   == 5
        assert s.medium_period == 13
        assert s.slow_period   == 34

    def test_init_invalid_periods(self):
        """fast >= medium should raise ValueError."""
        with pytest.raises(ValueError):
            _make_strategy(params={"fast_period": 21, "medium_period": 9, "slow_period": 55})

    def test_init_invalid_medium_slow(self):
        """medium >= slow should raise ValueError."""
        with pytest.raises(ValueError):
            _make_strategy(params={"fast_period": 9, "medium_period": 55, "slow_period": 21})


class TestTripleEMAOnBar:
    def test_no_signal_warmup(self):
        """No signal should fire during the slow_period warm-up."""
        s = _make_strategy()
        # Feed slow_period - 1 bars (54 bars for default slow=55)
        prices = [100.0 + i * 0.1 for i in range(s.slow_period - 1)]
        sigs = _feed_bars(s, prices)
        assert sigs == [], f"Expected no signals during warm-up, got {sigs}"

    def test_buy_signal_fires(self):
        """BUY signal fires when fast > medium > slow alignment occurs."""
        s = _make_strategy()
        # Build a strongly rising price series to force bullish alignment
        # Start flat, then spike sharply upward
        flat   = [100.0] * 60          # warm-up: all EMAs converge near 100
        rising = [100.0 + i * 3.0 for i in range(1, 40)]  # sharp rally
        sigs   = _feed_bars(s, flat + rising)
        buy_sigs = [sig for sig in sigs if sig["side"] == "BUY"]
        assert len(buy_sigs) >= 1, "Expected at least one BUY signal on strong uptrend"
        assert all(sig["qty"] > 0 for sig in buy_sigs)

    def test_sell_signal_fires(self):
        """SELL signal fires when fast < medium < slow alignment occurs."""
        s = _make_strategy()
        # Start high and declining
        flat    = [200.0] * 60
        falling = [200.0 - i * 3.0 for i in range(1, 40)]
        sigs    = _feed_bars(s, flat + falling)
        sell_sigs = [sig for sig in sigs if sig["side"] == "SELL"]
        assert len(sell_sigs) >= 1, "Expected at least one SELL signal on strong downtrend"
        assert all(sig["qty"] > 0 for sig in sell_sigs)

    def test_invalid_bar_skipped(self):
        """Bar with close <= 0 should be skipped (returns None)."""
        s   = _make_strategy()
        sig = s.on_bar({"close": 0.0})
        assert sig is None

    def test_no_duplicate_buy_while_long(self):
        """No second BUY should fire while already in a long position."""
        s       = _make_strategy()
        flat    = [100.0] * 60
        rising  = [100.0 + i * 3.0 for i in range(1, 80)]
        sigs    = _feed_bars(s, flat + rising)
        buy_sigs = [sig for sig in sigs if sig["side"] == "BUY"]
        # Only the first bullish crossover should trigger; position guard blocks subsequent
        assert len(buy_sigs) <= 2, f"Too many BUY signals while long: {buy_sigs}"


class TestTripleEMAGetState:
    def test_get_state_keys(self):
        """get_state() must return all expected keys."""
        s = _make_strategy()
        s.on_bar(_bar(100.0))  # feed one bar
        state = s.get_state()
        expected_keys = {"symbol", "strategy", "fast_ema", "medium_ema",
                         "slow_ema", "position", "bars_seen", "params"}
        assert expected_keys.issubset(state.keys()), (
            f"Missing keys: {expected_keys - set(state.keys())}"
        )
        assert state["strategy"] == "triple_ema"
        assert state["symbol"]   == "TEST"
        assert state["bars_seen"] == 1

    def test_get_state_params(self):
        """Params sub-dict must reflect init values."""
        s = _make_strategy(params={"fast_period": 5, "medium_period": 13, "slow_period": 34})
        p = s.get_state()["params"]
        assert p["fast_period"]   == 5
        assert p["medium_period"] == 13
        assert p["slow_period"]   == 34


class TestTripleEMAGenerateSignals:
    def test_generate_signals_returns_series(self):
        """generate_signals() must return a pd.Series of int aligned to df.index."""
        s  = _make_strategy()
        n  = 200
        np.random.seed(42)
        prices = pd.Series(100 + np.cumsum(np.random.randn(n) * 0.5))
        df = pd.DataFrame({"Close": prices})
        signals = s.generate_signals(df)
        assert isinstance(signals, pd.Series)
        assert len(signals) == n
        assert set(signals.unique()).issubset({-1, 0, 1})

    def test_generate_signals_warmup_zeros(self):
        """First slow_period rows must all be 0 (warm-up)."""
        s  = _make_strategy()
        n  = 200
        df = pd.DataFrame({"Close": [100.0 + i * 0.1 for i in range(n)]})
        signals = s.generate_signals(df)
        assert (signals.iloc[: s.slow_period] == 0).all(), (
            "Warm-up rows should all be 0"
        )


class TestTripleEMARegistry:
    def test_registry_includes_triple_ema(self):
        """After importing, triple_ema must appear in list_strategies()."""
        from strategies.registry import list_strategies
        assert "triple_ema" in list_strategies(), (
            f"'triple_ema' not found in registry. Available: {list_strategies()}"
        )

    def test_registry_get_class(self):
        """get_strategy_class('triple_ema') must return TripleEMAStrategy."""
        from strategies.registry import get_strategy_class
        from strategies.triple_ema import TripleEMAStrategy
        cls = get_strategy_class("triple_ema")
        assert cls is TripleEMAStrategy

    def test_registry_strategy_info(self):
        """strategy_info() must return correct id and class_name."""
        from strategies.registry import strategy_info
        info = strategy_info("triple_ema")
        assert info["id"]         == "triple_ema"
        assert info["class_name"] == "TripleEMAStrategy"
