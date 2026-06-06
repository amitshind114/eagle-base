"""Phase-03 Risk + Sizer Certification Tests.

EXIT CRITERIA (all must pass before Phase 04 begins):
  1. PositionSizer(100_000).size("TEST",100,0.6,0.04,0.025,0.015).kelly_fraction
       must be between 0.1 and 0.4
  2. atr_pct=0 returns SMALLER qty than atr_pct=0.015 (not larger)
       Rationale: conservative when ATR unknown
  3. max_position_pct hard cap enforced:
       qty * price <= capital * max_position_pct  (within 1 share rounding)
  4. Negative Kelly (no edge) → qty=0
  5. Degenerate inputs (avg_win=0 or avg_loss=0) → returns -1.0 sentinel
  6. half_kelly is always Kelly/2
  7. validate_params: fast >= slow → False
  8. validate_params: period <= 2 → False
  9. _REGISTRY_LOCK exists on strategies.base module

Run with:
    pytest tests/cert_sizer.py -v
"""

from __future__ import annotations

import threading
import pytest

from risk.sizer import PositionSizer, SizeResult


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

CAPITAL      = 100_000.0
PRICE        = 100.0
WIN_RATE     = 0.6
AVG_WIN      = 0.04     # 4%   as decimal
AVG_LOSS     = 0.025    # 2.5% as decimal
ATR_KNOWN    = 0.015    # 1.5% as decimal
ATR_UNKNOWN  = 0.0      # unavailable


def _sizer(max_pos: float = 0.10) -> PositionSizer:
    return PositionSizer(total_capital=CAPITAL, max_position_pct=max_pos)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Kelly fraction range — core exit criterion
# ─────────────────────────────────────────────────────────────────────────────

class TestKellyFractionRange:
    def test_kelly_fraction_in_expected_range(self):
        """With W=0.6, avg_win=0.04, avg_loss=0.025 → half-Kelly in (0.1, 0.4).

        Correct Kelly:
            b = 0.04 / 0.025 = 1.6
            f* = (0.6*1.6 - 0.4) / 1.6 = 0.56/1.6 = 0.35
            half_kelly = 0.175  → inside (0.1, 0.4) ✓
        """
        result = _sizer().size("TEST", PRICE, WIN_RATE, AVG_WIN, AVG_LOSS, ATR_KNOWN)
        assert 0.1 < result.kelly_fraction < 0.4, (
            f"kelly_fraction={result.kelly_fraction:.4f} expected in (0.1, 0.4). "
            f"Rationale: {result.rationale}"
        )

    def test_kelly_formula_exact(self):
        """Raw Kelly = 0.35, half_kelly = 0.175 for known inputs."""
        sizer      = _sizer()
        raw_kelly  = sizer._kelly(WIN_RATE, AVG_WIN, AVG_LOSS)
        half_kelly = raw_kelly / 2.0
        assert abs(raw_kelly - 0.35) < 0.001, f"raw Kelly should be ≈0.35, got {raw_kelly}"
        assert abs(half_kelly - 0.175) < 0.001, f"half Kelly should be ≈0.175, got {half_kelly}"

    def test_half_kelly_is_always_kelly_over_2(self):
        """half_kelly returned by size() == _kelly() / 2 for any valid inputs."""
        test_cases = [
            (0.55, 0.03, 0.02),
            (0.65, 0.06, 0.03),
            (0.45, 0.05, 0.025),
        ]
        sizer = _sizer()
        for wr, aw, al in test_cases:
            raw     = sizer._kelly(wr, aw, al)
            expected_half = max(raw / 2.0, 0.0)
            result  = sizer.size("X", PRICE, wr, aw, al, ATR_KNOWN)
            assert abs(result.kelly_fraction - expected_half) < 1e-9, (
                f"half_kelly mismatch for W={wr}: got {result.kelly_fraction}, "
                f"expected {expected_half}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Vol scalar — atr=0 must return SMALLER qty (conservative)
# ─────────────────────────────────────────────────────────────────────────────

class TestVolScalar:
    def test_atr_zero_returns_smaller_qty_than_atr_known(self):
        """atr=0 → vol_scalar=0.5 → smaller position than atr=0.015.

        This was the bug: the old code returned vol_scalar=2.0 when ATR
        was unknown — the largest possible bet on the worst possible data.
        Fixed: vol_scalar=0.5 when atr_pct <= 0.
        """
        r_unknown = _sizer().size("T", PRICE, WIN_RATE, AVG_WIN, AVG_LOSS, ATR_UNKNOWN)
        r_known   = _sizer().size("T", PRICE, WIN_RATE, AVG_WIN, AVG_LOSS, ATR_KNOWN)
        assert r_unknown.qty < r_known.qty or (
            r_unknown.qty == 0 and r_known.qty == 0
        ), (
            f"atr=0 should give SMALLER qty than atr=0.015. "
            f"Got atr=0: qty={r_unknown.qty}, atr=0.015: qty={r_known.qty}"
        )

    def test_atr_zero_vol_scalar_is_0_5(self):
        """_vol_scalar(0) must return exactly 0.5."""
        scalar = _sizer()._vol_scalar(0.0)
        assert scalar == 0.5, f"vol_scalar(0) should be 0.5, got {scalar}"

    def test_atr_negative_vol_scalar_is_0_5(self):
        """_vol_scalar(<0) also returns 0.5 (bad data guard)."""
        scalar = _sizer()._vol_scalar(-0.01)
        assert scalar == 0.5, f"vol_scalar(-0.01) should be 0.5, got {scalar}"

    def test_atr_known_vol_scalar_clamped(self):
        """vol_scalar for known ATR is clamped to [0.25, 2.0]."""
        scalar = _sizer()._vol_scalar(ATR_KNOWN)
        assert 0.25 <= scalar <= 2.0, f"vol_scalar should be in [0.25, 2.0], got {scalar}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Max position cap
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxPositionCap:
    def test_position_value_never_exceeds_cap(self):
        """qty * price <= capital * max_position_pct (within 1 share rounding)."""
        max_pct = 0.10
        result  = _sizer(max_pct).size("T", PRICE, WIN_RATE, AVG_WIN, AVG_LOSS, ATR_KNOWN)
        cap     = CAPITAL * max_pct
        # Allow 1 share of rounding tolerance
        assert result.position_value <= cap + PRICE, (
            f"position_value={result.position_value} exceeds cap={cap}"
        )

    def test_position_pct_never_exceeds_max_position_pct(self):
        """result.position_pct <= max_position_pct always."""
        for max_pct in (0.05, 0.10, 0.20):
            result = _sizer(max_pct).size("T", PRICE, WIN_RATE, AVG_WIN, AVG_LOSS, ATR_KNOWN)
            assert result.position_pct <= max_pct + 1e-9, (
                f"position_pct={result.position_pct} > max={max_pct}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Negative Kelly → qty = 0
# ─────────────────────────────────────────────────────────────────────────────

class TestNegativeKelly:
    def test_negative_edge_returns_zero_qty(self):
        """win_rate=0.4, avg_win=0.01, avg_loss=0.05 → negative Kelly → qty=0.

        Kelly = (0.4*0.2 - 0.6) / 0.2 = (0.08 - 0.6) / 0.2 = -2.6  (negative)
        This means no statistical edge — sizer must return qty=0.
        """
        result = _sizer().size("BAD", PRICE, 0.4, 0.01, 0.05, ATR_KNOWN)
        assert result.qty == 0, (
            f"Negative Kelly should give qty=0, got {result.qty}. "
            f"Rationale: {result.rationale}"
        )

    def test_negative_kelly_fraction_stored(self):
        """kelly_fraction stored on zero-qty result is <= 0."""
        result = _sizer().size("BAD", PRICE, 0.4, 0.01, 0.05, ATR_KNOWN)
        assert result.kelly_fraction <= 0, (
            f"kelly_fraction on no-edge trade should be <= 0, got {result.kelly_fraction}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Degenerate inputs — guard returns -1.0
# ─────────────────────────────────────────────────────────────────────────────

class TestDegenerateInputs:
    def test_avg_win_zero_returns_sentinel(self):
        """_kelly() with avg_win=0 returns -1.0 sentinel."""
        sizer = _sizer()
        assert sizer._kelly(0.6, 0.0, 0.025) == -1.0

    def test_avg_loss_zero_returns_sentinel(self):
        """_kelly() with avg_loss=0 returns -1.0 sentinel."""
        sizer = _sizer()
        assert sizer._kelly(0.6, 0.04, 0.0) == -1.0

    def test_degenerate_size_returns_zero_qty(self):
        """size() with avg_win=0 returns qty=0 (not crash)."""
        result = _sizer().size("X", PRICE, 0.6, 0.0, 0.025, ATR_KNOWN)
        assert result.qty == 0

    def test_price_zero_returns_zero_qty(self):
        """size() with price=0 returns qty=0 (not ZeroDivisionError)."""
        result = _sizer().size("X", 0.0, 0.6, AVG_WIN, AVG_LOSS, ATR_KNOWN)
        assert result.qty == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Thread safety — _REGISTRY_LOCK exists
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistryLock:
    def test_registry_lock_exists(self):
        """_REGISTRY_LOCK must be a threading.Lock on strategies.base."""
        import strategies.base as sb
        assert hasattr(sb, "_REGISTRY_LOCK"), "_REGISTRY_LOCK missing from strategies.base"
        # It must be an instance that can be used as a context manager (Lock or RLock)
        lock = sb._REGISTRY_LOCK
        assert hasattr(lock, "acquire") and hasattr(lock, "release"), (
            "_REGISTRY_LOCK must be a threading.Lock or RLock"
        )

    def test_concurrent_register_does_not_corrupt(self):
        """Registering 50 strategies concurrently must not corrupt the registry."""
        import strategies.base as sb
        from strategies.base import BaseStrategy, register_strategy
        import pandas as pd

        results = []

        def _make_and_register(i: int):
            # Dynamically create and register a strategy class
            cls = type(
                f"ConcurrentStrat{i}",
                (BaseStrategy,),
                {
                    "name": f"ConcurrentStrat{i}",
                    "generate_signals": lambda self, df: pd.Series(0, index=df.index),
                },
            )
            register_strategy(cls)
            results.append(cls.name)

        threads = [threading.Thread(target=_make_and_register, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 50 must be registered
        for i in range(50):
            assert f"ConcurrentStrat{i}" in sb._STRATEGY_REGISTRY, (
                f"ConcurrentStrat{i} missing after concurrent registration"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 7 & 8. validate_params base guards
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateParams:
    def _concrete_strategy(self):
        """Minimal concrete BaseStrategy for testing validate_params."""
        from strategies.base import BaseStrategy
        import pandas as pd

        class _Concrete(BaseStrategy):
            name = "_TestConcrete"
            def generate_signals(self, df):
                return pd.Series(0, index=df.index)

        return _Concrete()

    def test_fast_greater_than_slow_is_invalid(self):
        """SmaCrossover(fast=50, slow=20) — fast >= slow must return False."""
        s = self._concrete_strategy()
        assert s.validate_params({"fast": 50, "slow": 20}) is False

    def test_fast_equals_slow_is_invalid(self):
        """fast == slow is also invalid."""
        s = self._concrete_strategy()
        assert s.validate_params({"fast": 20, "slow": 20}) is False

    def test_fast_less_than_slow_is_valid(self):
        """fast=20, slow=50 is valid."""
        s = self._concrete_strategy()
        assert s.validate_params({"fast": 20, "slow": 50}) is True

    def test_period_too_small_is_invalid(self):
        """period <= 2 must return False."""
        s = self._concrete_strategy()
        assert s.validate_params({"period": 2}) is False
        assert s.validate_params({"period": 1}) is False
        assert s.validate_params({"period": 0}) is False

    def test_period_valid(self):
        """period=14 is valid."""
        s = self._concrete_strategy()
        assert s.validate_params({"period": 14}) is True

    def test_fast_zero_is_invalid(self):
        """fast=0 must return False even if slow > fast."""
        s = self._concrete_strategy()
        assert s.validate_params({"fast": 0, "slow": 20}) is False

    def test_unrelated_params_pass(self):
        """Params without fast/slow/period pass base validation."""
        s = self._concrete_strategy()
        assert s.validate_params({"threshold": 0.5, "multiplier": 2}) is True
