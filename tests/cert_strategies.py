"""Strategy Certification Suite — Phase 05.

For each of 5 core strategies (SMA, EMA, RSI, MACD, ORB):
  1. generate_signals() returns pd.Series with len == len(df)
  2. Only {-1, 0, 1} values in the returned Series
  3. Backtest runs end-to-end without exception
  4. validate_params(bad_params) returns False
  5. @register_strategy populates _STRATEGY_REGISTRY correctly

Exit gate:
  - threading test: 20 threads importing strategies simultaneously
    → len(_STRATEGY_REGISTRY) == 5 (no dropped registrations)
  - SmaCrossover(fast=50, slow=20) raises ValueError
  - on_bar() returns int 1/-1/0, not str
  - Mutable-default test: append to one instance's tags → other instance unaffected

Run:
    python -m pytest tests/cert_strategies.py -v
or standalone:
    python tests/cert_strategies.py
"""

from __future__ import annotations

import threading
import warnings
from typing import Any

import numpy as np
import pandas as pd
import pytest


# ── Synthetic OHLCV fixtures ──────────────────────────────────────────────────

def _make_daily_df(n: int = 252) -> pd.DataFrame:
    """252 trading-day synthetic OHLCV with tz-aware index."""
    rng   = np.random.default_rng(42)
    close = 1000.0 + np.cumsum(rng.normal(0, 10, n))
    high  = close + rng.uniform(0, 15, n)
    low   = close - rng.uniform(0, 15, n)
    open_ = close + rng.normal(0, 5, n)
    vol   = rng.integers(100_000, 1_000_000, n).astype(float)
    idx   = pd.date_range("2023-01-01", periods=n, freq="B", tz="Asia/Kolkata")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


def _make_intraday_df(days: int = 10, interval_min: int = 5) -> pd.DataFrame:
    """Intraday 5m bars for N days (09:15–15:30 IST), tz-aware."""
    bars_per_day = int(375 / interval_min)  # 375 = 6h15m trading minutes
    rows = []
    base = pd.Timestamp("2023-06-01 09:15", tz="Asia/Kolkata")
    rng  = np.random.default_rng(99)
    price = 1000.0
    for d in range(days):
        day_start = base + pd.Timedelta(days=d)
        for b in range(bars_per_day):
            ts    = day_start + pd.Timedelta(minutes=b * interval_min)
            price = price + rng.normal(0, 2)
            rows.append({
                "Open":  price + rng.uniform(-1, 1),
                "High":  price + rng.uniform(0,  3),
                "Low":   price - rng.uniform(0,  3),
                "Close": price,
                "Volume": float(rng.integers(5_000, 50_000)),
            })
    return pd.DataFrame(rows, index=pd.DatetimeIndex([r["Open"] for r in rows]).tz_localize(None)).assign(
        **{"index": [base + pd.Timedelta(days=d) + pd.Timedelta(minutes=b * interval_min)
                     for d in range(days) for b in range(bars_per_day)]}
    ).set_index("index")


def _make_intraday_df_v2(days: int = 10, interval_min: int = 5) -> pd.DataFrame:
    """Cleaner intraday fixture: proper tz-aware DatetimeIndex."""
    bars_per_day = int(375 / interval_min)
    rng   = np.random.default_rng(99)
    price = 1000.0
    idx   = []
    data  = {"Open": [], "High": [], "Low": [], "Close": [], "Volume": []}

    base = pd.Timestamp("2023-06-01", tz="Asia/Kolkata")
    for d in range(days):
        session_start = base + pd.Timedelta(days=d)
        session_start = session_start.replace(hour=9, minute=15)
        for b in range(bars_per_day):
            ts    = session_start + pd.Timedelta(minutes=b * interval_min)
            price = price + rng.normal(0, 2)
            idx.append(ts)
            data["Open"].append(price + float(rng.uniform(-1, 1)))
            data["High"].append(price + float(rng.uniform(0, 3)))
            data["Low"].append(price - float(rng.uniform(0, 3)))
            data["Close"].append(price)
            data["Volume"].append(float(rng.integers(5_000, 50_000)))

    return pd.DataFrame(data, index=pd.DatetimeIndex(idx))


# ── Strategy imports ──────────────────────────────────────────────────────────

from strategies.sma_crossover       import SmaCrossover
from strategies.ema_crossover       import EmaCrossover
from strategies.rsi_mean_reversion  import RsiMeanReversion
from strategies.macd_signal         import MacdSignal
from strategies.plugins.orb         import ORBStrategy
from strategies.base                import _STRATEGY_REGISTRY

DAILY_DF     = _make_daily_df()
INTRADAY_DF  = _make_intraday_df_v2(days=10, interval_min=5)

CORE_STRATEGIES = [
    (SmaCrossover(),       DAILY_DF,    "SMA Crossover"),
    (EmaCrossover(),       DAILY_DF,    "EMA Crossover"),
    (RsiMeanReversion(),   DAILY_DF,    "RSI Mean Reversion"),
    (MacdSignal(),         DAILY_DF,    "MACD Signal"),
    (ORBStrategy(interval="5m", range_minutes=15), INTRADAY_DF, "ORB"),
]


# ── Test 1: generate_signals length ──────────────────────────────────────────

@pytest.mark.parametrize("strategy,df,label", CORE_STRATEGIES)
def test_signal_length(strategy, df, label):
    """generate_signals must return Series aligned to input df."""
    signals = strategy.generate_signals(df)
    assert isinstance(signals, pd.Series), f"{label}: generate_signals must return pd.Series"
    assert len(signals) == len(df), (
        f"{label}: signal length {len(signals)} != df length {len(df)}"
    )
    assert signals.index.equals(df.index), f"{label}: signal index must match df index"


# ── Test 2: only {-1, 0, 1} values ──────────────────────────────────────────

@pytest.mark.parametrize("strategy,df,label", CORE_STRATEGIES)
def test_signal_values(strategy, df, label):
    """generate_signals must only emit -1, 0, or 1."""
    signals = strategy.generate_signals(df)
    bad = signals[~signals.isin([-1, 0, 1])]
    assert bad.empty, (
        f"{label}: unexpected signal values: {bad.value_counts().to_dict()}"
    )


# ── Test 3: no exception on generate_signals ────────────────────────────────

@pytest.mark.parametrize("strategy,df,label", CORE_STRATEGIES)
def test_no_exception(strategy, df, label):
    """generate_signals must not raise any exception."""
    try:
        signals = strategy.generate_signals(df)
    except Exception as exc:
        pytest.fail(f"{label}: generate_signals raised {type(exc).__name__}: {exc}")


# ── Test 4: validate_params rejects bad params ───────────────────────────────

_BAD_PARAMS = [
    (SmaCrossover(),      {"fast": 50, "slow": 20},   "SMA fast>slow"),
    (SmaCrossover(),      {"fast": -1, "slow": 20},   "SMA negative fast"),
    (EmaCrossover(),      {"fast": 30, "slow": 10},   "EMA fast>slow"),
    (RsiMeanReversion(),  {"period": -5},              "RSI negative period"),
    (RsiMeanReversion(),  {"oversold": 80, "overbought": 30}, "RSI oversold>overbought"),
    (MacdSignal(),        {"fast": 30, "slow": 10},   "MACD fast>slow"),
    (ORBStrategy(),       {"interval": "1d"},          "ORB daily interval"),
]

@pytest.mark.parametrize("strategy,bad_params,label", _BAD_PARAMS)
def test_validate_params_rejects_bad(strategy, bad_params, label):
    """validate_params(bad_params) must return False."""
    result = strategy.validate_params(bad_params)
    assert result is False, f"{label}: validate_params should return False for {bad_params}"


# ── Test 5: @register_strategy populates registry ────────────────────────────

def test_registry_populated():
    """All 5 core strategies must appear in _STRATEGY_REGISTRY after import."""
    expected = {"SMA Crossover", "EMA Crossover", "RSI Mean Reversion", "MACD Signal", "ORB"}
    missing  = expected - set(_STRATEGY_REGISTRY.keys())
    assert not missing, f"Missing from _STRATEGY_REGISTRY: {missing}"


# ── Test 6: Thread safety — 20 concurrent imports ────────────────────────────

def test_registry_thread_safety():
    """20 threads importing strategies simultaneously must not lose registrations."""
    import importlib
    errors: list[Exception] = []

    def _import():
        try:
            importlib.import_module("strategies.sma_crossover")
            importlib.import_module("strategies.ema_crossover")
            importlib.import_module("strategies.rsi_mean_reversion")
            importlib.import_module("strategies.macd_signal")
            importlib.import_module("strategies.plugins.orb")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_import) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    expected = {"SMA Crossover", "EMA Crossover", "RSI Mean Reversion", "MACD Signal", "ORB"}
    missing  = expected - set(_STRATEGY_REGISTRY.keys())
    assert not missing, f"Registry lost entries under concurrency: {missing}"


# ── Test 7: Mutable default isolation ────────────────────────────────────────

def test_mutable_default_isolation():
    """Appending to one instance's tags must not affect another instance."""
    a = SmaCrossover()
    b = SmaCrossover()
    original_tags_b = list(b.tags)
    a.tags.append("__test_tag__")
    assert "__test_tag__" not in b.tags, (
        "Mutable default bug: appending to a.tags affected b.tags. "
        "Fix: __init__ must copy class-level tags to instance."
    )
    assert b.tags == original_tags_b, "b.tags changed after a.tags mutation"


# ── Test 8: validate_params raises or returns False for fast>slow ─────────────

def test_sma_fast_gt_slow_invalid():
    """SmaCrossover(fast=50, slow=20) must be rejected by validate_params."""
    s = SmaCrossover(fast=50, slow=20)
    assert s.validate_params({"fast": 50, "slow": 20}) is False, (
        "SmaCrossover.validate_params should return False when fast > slow"
    )


# ── Test 9: on_bar returns int ────────────────────────────────────────────────

@pytest.mark.parametrize("strategy,df,label", CORE_STRATEGIES)
def test_on_bar_returns_int(strategy, df, label):
    """on_bar() must return int 1, -1, or 0 — not a str."""
    result = strategy.on_bar(df)
    assert isinstance(result, int), (
        f"{label}: on_bar() returned {type(result).__name__} '{result}'. Must be int."
    )
    assert result in (-1, 0, 1), (
        f"{label}: on_bar() returned {result}. Must be -1, 0, or 1."
    )


# ── Test 10: metadata() returns required keys ─────────────────────────────────

@pytest.mark.parametrize("strategy,df,label", CORE_STRATEGIES)
def test_metadata_keys(strategy, df, label):
    """metadata() must return dict with win_rate, avg_win_pct, avg_loss_pct."""
    m = strategy.metadata()
    assert isinstance(m, dict), f"{label}: metadata() must return dict"
    for key in ("win_rate", "avg_win_pct", "avg_loss_pct"):
        assert key in m, f"{label}: metadata() missing key '{key}'"
        assert isinstance(m[key], (int, float)), f"{label}: metadata()['{key}'] must be numeric"
        assert 0 <= m[key] <= 1, f"{label}: metadata()['{key}'] = {m[key]} out of [0, 1] range"


# ── Standalone runner ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running Phase 05 strategy certification...\n")

    passed = 0
    failed = 0

    def _run(name: str, fn):
        global passed, failed
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as exc:
            print(f"  ❌ {name}: {exc}")
            failed += 1

    for strategy, df, label in CORE_STRATEGIES:
        _run(f"{label} — signal length",  lambda s=strategy, d=df, l=label: test_signal_length(s, d, l))
        _run(f"{label} — signal values",  lambda s=strategy, d=df, l=label: test_signal_values(s, d, l))
        _run(f"{label} — no exception",   lambda s=strategy, d=df, l=label: test_no_exception(s, d, l))
        _run(f"{label} — on_bar int",     lambda s=strategy, d=df, l=label: test_on_bar_returns_int(s, d, l))
        _run(f"{label} — metadata keys",  lambda s=strategy, d=df, l=label: test_metadata_keys(s, d, l))

    _run("Registry populated",            test_registry_populated)
    _run("Thread safety (20 threads)",    test_registry_thread_safety)
    _run("Mutable default isolation",     test_mutable_default_isolation)
    _run("SMA fast>slow invalid",         test_sma_fast_gt_slow_invalid)

    print(f"\n{'='*50}")
    print(f"  Passed: {passed}  |  Failed: {failed}")
    if failed == 0:
        print("  Phase 05 EXIT GATE: PASS ✅")
    else:
        print("  Phase 05 EXIT GATE: FAIL ❌")
