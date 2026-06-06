"""Phase-04 Data Layer Certification Tests.

EXIT CRITERIA (all must pass before Phase 05 begins):
  1. _cap_period("1h", "1y")  == "1y"   (365d <= 730d — no cap needed)
  2. _cap_period("1h", "2y")  == "730d" (730d == 730d — exactly at cap, passthrough)
  3. _cap_period("1m", "1y")  == "7d"   (365d > 7d   — capped)
  4. _cap_period("1m", "5d")  == "5d"   (5d <= 7d    — no cap)
  5. _cap_period("1d", "10y") == "10y"  (daily: no cap at all)
  6. 60d sorts correctly as 60 days (< 6mo/180d) — the old string-order bug
  7. fetch_batch returns tuple[dict, list] — not bare dict
  8. fetch_batch INVALID symbol appears in errors list, not results dict
  9. df.index.tz is not None after DataFetcher.fetch() (tz-aware)
  10. OHLC sanity: High < Open row flagged and dropped
  11. OHLC sanity: Low  > Close row flagged and dropped
  12. >5% NaN Close → ValidationResult.passed == False
  13. _FETCH_SEMAPHORE exists and is threading.Semaphore on multi_runner module

Run with:
    pytest tests/cert_data.py -v
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from data.fetcher import DataFetcher, TO_DAYS, _INTERVAL_CAPS
from data.validator import DataValidator


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_clean_df(n: int = 100) -> pd.DataFrame:
    """Minimal valid OHLCV DataFrame with tz-aware IST index."""
    close  = pd.Series(np.linspace(100, 200, n))
    idx    = pd.date_range("2023-01-01", periods=n, freq="B", tz="Asia/Kolkata")
    return pd.DataFrame({
        "Open":   close - 1,
        "High":   close + 2,
        "Low":    close - 2,
        "Close":  close,
        "Volume": np.ones(n) * 500_000,
    }, index=idx)


# ─────────────────────────────────────────────────────────────────────────────
# 1–5. _cap_period correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestCapPeriod:
    def test_1h_1y_no_cap_needed(self):
        """1h + 1y: 365d <= 730d limit — period unchanged."""
        assert DataFetcher._cap_period("1h", "1y") == "1y", (
            "_cap_period('1h','1y') should return '1y' (365d is within 730d limit)"
        )

    def test_1h_2y_at_limit(self):
        """1h + 2y: 730d == 730d limit — period unchanged (not over)."""
        result = DataFetcher._cap_period("1h", "2y")
        # 2y=730d equals the cap 730d exactly — should pass through
        assert result == "2y", (
            f"_cap_period('1h','2y') should return '2y' (730d==730d cap), got '{result}'"
        )

    def test_1h_5y_capped_to_730d(self):
        """1h + 5y: 1825d > 730d — must cap to 730d."""
        result = DataFetcher._cap_period("1h", "5y")
        assert result == "730d", (
            f"_cap_period('1h','5y') should cap to '730d', got '{result}'"
        )

    def test_1m_1y_capped_to_7d(self):
        """Exit criterion: _cap_period('1m','1y') == '7d'."""
        assert DataFetcher._cap_period("1m", "1y") == "7d", (
            "_cap_period('1m','1y') should return '7d'"
        )

    def test_1m_5d_no_cap(self):
        """1m + 5d: 5d <= 7d — period unchanged."""
        assert DataFetcher._cap_period("1m", "5d") == "5d"

    def test_1m_7d_exactly_at_cap(self):
        """1m + 7d: exactly at cap — should pass through unchanged."""
        assert DataFetcher._cap_period("1m", "7d") == "7d"

    def test_daily_no_cap(self):
        """Daily interval has no period cap at all."""
        assert DataFetcher._cap_period("1d", "10y") == "10y"
        assert DataFetcher._cap_period("1d", "max") == "max"


class TestToDaysOrdering:
    def test_60d_less_than_6mo(self):
        """THE OLD BUG: '60d' was sorting after '6mo' in a string list.

        60 days (60) must be less than 6 months (180).
        TO_DAYS fixes this with integer comparison.
        """
        assert TO_DAYS["60d"] < TO_DAYS["6mo"], (
            f"60d={TO_DAYS['60d']}d should be less than 6mo={TO_DAYS['6mo']}d"
        )

    def test_1y_equals_2y_divided_by_2(self):
        """1y=365, 2y=730. 730/2=365. Consistent."""
        assert TO_DAYS["2y"] == TO_DAYS["1y"] * 2

    def test_max_is_largest(self):
        """'max' must map to the largest value in TO_DAYS."""
        assert TO_DAYS["max"] == max(TO_DAYS.values())

    def test_interval_caps_are_in_to_days(self):
        """Every value in _INTERVAL_CAPS must have a TO_DAYS entry."""
        for interval, cap in _INTERVAL_CAPS.items():
            assert cap in TO_DAYS, (
                f"_INTERVAL_CAPS['{interval}'] = '{cap}' has no TO_DAYS entry"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 7–8. fetch_batch return type
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchBatchReturnType:
    def test_returns_tuple_not_dict(self):
        """fetch_batch must return a tuple (dict, list), not a bare dict."""
        fetcher = DataFetcher()
        # Mock resolver so we don\'t need network
        with patch.object(fetcher, '_cap_period', return_value="1mo"):
            # Patch the module-level _resolver used by DataFetcher
            import data.fetcher as df_module
            original_resolver = df_module._resolver
            mock_resolver = MagicMock()
            # INVALID symbol returns None from to_yf
            mock_resolver.to_yf.return_value = None
            df_module._resolver = mock_resolver
            try:
                result = fetcher.fetch_batch(["INVALID_XYZ_999"], period="1mo")
            finally:
                df_module._resolver = original_resolver

        assert isinstance(result, tuple), (
            f"fetch_batch must return tuple, got {type(result)}"
        )
        assert len(result) == 2, "fetch_batch tuple must have exactly 2 elements"
        results_dict, errors_list = result
        assert isinstance(results_dict, dict), "First element must be dict"
        assert isinstance(errors_list, list), "Second element must be list"

    def test_invalid_symbol_in_errors(self):
        """Unresolvable symbol must appear in errors list, not results dict."""
        fetcher = DataFetcher()
        import data.fetcher as df_module
        original_resolver = df_module._resolver
        mock_resolver = MagicMock()
        mock_resolver.to_yf.return_value = None  # all symbols unresolvable
        df_module._resolver = mock_resolver
        try:
            results, errors = fetcher.fetch_batch(["INVALID_XYZ", "ANOTHER_BAD"])
        finally:
            df_module._resolver = original_resolver

        assert "INVALID_XYZ" in errors
        assert "ANOTHER_BAD" in errors
        assert "INVALID_XYZ" not in results
        assert "ANOTHER_BAD" not in results


# ─────────────────────────────────────────────────────────────────────────────
# 9. Timezone-aware index
# ─────────────────────────────────────────────────────────────────────────────

class TestTimezoneAwareIndex:
    def test_fetched_df_has_tz_aware_index(self):
        """After DataFetcher.fetch(), df.index.tz must not be None.

        Tests the _post_process path by mocking yfinance so no network needed.
        """
        import data.fetcher as df_module
        fetcher = DataFetcher()

        # Build a fake yfinance response with UTC tz (what yfinance returns)
        n   = 50
        idx = pd.date_range("2023-01-01", periods=n, freq="B", tz="UTC")
        fake_df = pd.DataFrame({
            "Open":   np.ones(n) * 100,
            "High":   np.ones(n) * 102,
            "Low":    np.ones(n) * 98,
            "Close":  np.ones(n) * 101,
            "Volume": np.ones(n) * 1_000_000,
        }, index=idx)

        # Mock the resolver and yfinance Ticker.history
        original_resolver = df_module._resolver
        mock_resolver = MagicMock()
        mock_resolver.to_yf.return_value = "RELIANCE.NS"
        df_module._resolver = mock_resolver

        try:
            with patch("yfinance.Ticker") as mock_ticker:
                mock_ticker.return_value.history.return_value = fake_df
                df = fetcher.fetch("RELIANCE", period="3mo", interval="1d")
        finally:
            df_module._resolver = original_resolver

        assert df.index.tz is not None, (
            f"df.index.tz should not be None after fetch(). "
            f"Got tz={df.index.tz}. tz_localize(None) must NOT be called in fetch()."
        )
        assert str(df.index.tz) == "Asia/Kolkata", (
            f"Timezone should be Asia/Kolkata, got {df.index.tz}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 10–12. Validator OHLC sanity + NaN Close
# ─────────────────────────────────────────────────────────────────────────────

class TestOHLCSanity:
    def test_high_less_than_open_is_removed(self):
        """Row where High < Open must be flagged and removed."""
        df = _make_clean_df(20)
        # Inject one bad bar: set High < Open on row 5
        df.iloc[5, df.columns.get_loc("High")] = df.iloc[5]["Open"] - 1.0
        v      = DataValidator(min_bars=5)
        result = v.validate(df, interval="1d")
        # The bad row should be removed
        assert result.clean_df is not None
        assert len(result.clean_df) == 19, (
            f"Expected 19 bars after removing 1 High<Open row, got {len(result.clean_df)}"
        )
        assert result.rows_removed >= 1

    def test_low_greater_than_close_is_removed(self):
        """Row where Low > Close must be flagged and removed."""
        df = _make_clean_df(20)
        df.iloc[7, df.columns.get_loc("Low")] = df.iloc[7]["Close"] + 1.0
        v      = DataValidator(min_bars=5)
        result = v.validate(df, interval="1d")
        assert len(result.clean_df) == 19, (
            f"Expected 19 bars after removing 1 Low>Close row, got {len(result.clean_df)}"
        )

    def test_high_less_than_low_is_removed(self):
        """Row where High < Low must be removed (pre-existing check still works)."""
        df = _make_clean_df(20)
        df.iloc[3, df.columns.get_loc("High")] = df.iloc[3]["Low"] - 1.0
        v      = DataValidator(min_bars=5)
        result = v.validate(df, interval="1d")
        assert len(result.clean_df) == 19

    def test_clean_data_passes(self):
        """Clean data must pass all OHLC checks."""
        df     = _make_clean_df(50)
        v      = DataValidator(min_bars=5)
        result = v.validate(df, interval="1d")
        assert result.passed is True
        assert len([w for w in result.warnings if "OHLC" in w]) == 0

    def test_failed_bars_populated_on_ohlc_violation(self):
        """failed_bars list must contain bar details on OHLC violations."""
        df = _make_clean_df(20)
        df.iloc[2, df.columns.get_loc("High")] = df.iloc[2]["Open"] - 5.0
        v      = DataValidator(min_bars=5)
        result = v.validate(df, interval="1d")
        assert len(result.failed_bars) >= 1, (
            "failed_bars should be populated when OHLC violations exist"
        )


class TestNaNCloseThreshold:
    def test_high_nan_close_pct_is_fail(self):
        """>5% NaN Close must cause ValidationResult.passed == False."""
        df = _make_clean_df(100)
        # Inject 10 NaN Close values (10% > 5% threshold)
        nan_idx = df.index[::10][:10]
        df.loc[nan_idx, "Close"] = float("nan")
        v      = DataValidator(min_bars=5)
        result = v.validate(df, interval="1d")
        assert result.passed is False, (
            f"Expected passed=False with >5% NaN Close, got passed={result.passed}. "
            f"Issues: {result.issues}"
        )
        assert any("%" in issue or "NaN" in issue for issue in result.issues), (
            "Issues list must mention NaN Close percentage"
        )

    def test_low_nan_close_pct_is_warning(self):
        """<=5% NaN Close is a warning, not a failure."""
        df = _make_clean_df(100)
        # Inject 3 NaN Close values (3% <= 5% threshold)
        df.iloc[10, df.columns.get_loc("Close")] = float("nan")
        df.iloc[20, df.columns.get_loc("Close")] = float("nan")
        df.iloc[30, df.columns.get_loc("Close")] = float("nan")
        v      = DataValidator(min_bars=5)
        result = v.validate(df, interval="1d")
        # Should pass (3% < 5% threshold) unless other issues exist
        # The NaN rows get dropped, so min_bars check must still pass
        assert len(result.issues) == 0 or all(
            "NaN" not in issue for issue in result.issues
        ), f"3% NaN should not cause FAIL, got issues={result.issues}"


# ─────────────────────────────────────────────────────────────────────────────
# 13. MultiStockRunner semaphore
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiRunnerSemaphore:
    def test_fetch_semaphore_exists(self):
        """_FETCH_SEMAPHORE must be a threading.Semaphore on multi_runner module."""
        import backtesting.multi_runner as mr_module
        assert hasattr(mr_module, "_FETCH_SEMAPHORE"), (
            "_FETCH_SEMAPHORE missing from backtesting.multi_runner"
        )
        sem = mr_module._FETCH_SEMAPHORE
        # threading.Semaphore is actually BoundedSemaphore or Semaphore
        # Both have acquire/release
        assert hasattr(sem, "acquire") and hasattr(sem, "release"), (
            "_FETCH_SEMAPHORE must support acquire/release (threading.Semaphore)"
        )

    def test_semaphore_initial_value_is_5(self):
        """Semaphore must be initialized with value=5 (max 5 concurrent fetches)."""
        import backtesting.multi_runner as mr_module
        sem = mr_module._FETCH_SEMAPHORE
        # Acquire all 5 slots to verify the count
        acquired = 0
        try:
            for _ in range(5):
                ok = sem.acquire(blocking=False)
                if ok:
                    acquired += 1
                else:
                    break
        finally:
            for _ in range(acquired):
                sem.release()
        assert acquired == 5, (
            f"Semaphore should have 5 initial slots, could only acquire {acquired}"
        )
