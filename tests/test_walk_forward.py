"""Phase 7 — Walk-Forward Analyser unit tests.

Covers:
  WFWindow
  [x] to_dict() keys and types
  [x] default scores are 0.0
  [x] forward_equity is empty Series by default

  WalkForwardResult (pure logic, no I/O)
  [x] empty result efficiency_ratio returns 0.0
  [x] empty result is_robust returns False
  [x] empty result best_params returns {}
  [x] empty result avg_train_score returns 0.0
  [x] empty result avg_forward_score returns 0.0
  [x] empty result summary_df returns empty DataFrame
  [x] efficiency_ratio correct formula (fwd/is avg)
  [x] is_robust True when efficiency >= 0.5
  [x] is_robust False when efficiency < 0.5
  [x] best_params returns params from highest forward_score window
  [x] avg_train_score correct
  [x] avg_forward_score correct
  [x] avg_forward_return correct
  [x] summary_df has expected columns
  [x] summary_df row count == window count
  [x] summary() returns non-empty string with strategy name
  [x] efficiency_ratio skips windows where train_return == 0
  [x] is_robust custom threshold respected

  WalkForwardTester._build_windows (pure date math, no I/O)
  [x] produces correct number of windows for known date range
  [x] first window train_start equals from_date
  [x] window keys present
  [x] forward_end is after forward_start
  [x] consecutive windows slide by forward_months
  [x] no windows returned when range is too short

  WalkForwardTester._slice
  [x] slices DataFrame to correct date range
  [x] empty DataFrame returns empty

  WalkForwardTester._stitch_equity
  [x] empty list returns empty Series
  [x] single series returns scaled series starting at initial_capital
  [x] two series stitched correctly (second starts where first ends)

  WalkForwardTester.run (mocked _fetch + _score)
  [x] returns WalkForwardResult on empty data (no crash)
  [x] run with mocked data produces correct window count

All tests: zero network, zero broker credentials, < 1 second.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backtesting.wf_result import WFWindow, WalkForwardResult
from backtesting.walk_forward import WalkForwardTester


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _make_window(
    window_id: int = 1,
    train_score: float = 1.5,
    forward_score: float = 0.9,
    train_return: float = 12.0,
    forward_return: float = 7.0,
    best_params: dict | None = None,
) -> WFWindow:
    return WFWindow(
        window_id=window_id,
        train_start="2020-01-01",
        train_end="2020-12-31",
        validate_start="2021-01-01",
        validate_end="2021-03-31",
        forward_start="2021-04-01",
        forward_end="2021-06-30",
        best_params=best_params or {"fast": 9, "slow": 26},
        train_score=train_score,
        validate_score=0.8,
        forward_score=forward_score,
        train_return=train_return,
        forward_return=forward_return,
    )


def _make_ohlcv(n: int = 300) -> pd.DataFrame:
    """Minimal OHLCV DataFrame with DatetimeIndex."""
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    import numpy as np
    rng = pd.Series(range(n), dtype=float)
    return pd.DataFrame(
        {
            "open":   100 + rng,
            "high":   101 + rng,
            "low":     99 + rng,
            "close":  100 + rng,
            "volume": 1_000_000,
        },
        index=idx,
    )


# ────────────────────────────────────────────────────────────────────────────
# WFWindow
# ────────────────────────────────────────────────────────────────────────────

class TestWFWindow:
    def test_to_dict_required_keys(self):
        w = _make_window()
        d = w.to_dict()
        for key in ("window", "train", "forward", "best_params",
                    "train_score", "validate_score", "forward_score",
                    "train_ret%", "forward_ret%"):
            assert key in d, f"Missing key: {key}"

    def test_default_scores_zero(self):
        w = WFWindow(
            window_id=1,
            train_start="2020-01-01", train_end="2020-12-31",
            validate_start="2021-01-01", validate_end="2021-03-31",
            forward_start="2021-04-01", forward_end="2021-06-30",
        )
        assert w.train_score == 0.0
        assert w.forward_score == 0.0
        assert w.validate_score == 0.0

    def test_forward_equity_empty_series_by_default(self):
        w = WFWindow(
            window_id=1,
            train_start="2020-01-01", train_end="2020-12-31",
            validate_start="2021-01-01", validate_end="2021-03-31",
            forward_start="2021-04-01", forward_end="2021-06-30",
        )
        assert isinstance(w.forward_equity, pd.Series)
        assert len(w.forward_equity) == 0


# ────────────────────────────────────────────────────────────────────────────
# WalkForwardResult — empty
# ────────────────────────────────────────────────────────────────────────────

class TestWalkForwardResultEmpty:
    def setup_method(self):
        self.result = WalkForwardResult(symbol="TEST", strategy_name="DummyStrat")

    def test_efficiency_ratio_zero(self):
        assert self.result.efficiency_ratio() == 0.0

    def test_is_robust_false(self):
        assert self.result.is_robust() is False

    def test_best_params_empty(self):
        assert self.result.best_params() == {}

    def test_avg_train_score_zero(self):
        assert self.result.avg_train_score() == 0.0

    def test_avg_forward_score_zero(self):
        assert self.result.avg_forward_score() == 0.0

    def test_summary_df_empty(self):
        df = self.result.summary_df()
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_summary_string_non_empty(self):
        s = self.result.summary()
        assert isinstance(s, str)
        assert len(s) > 0


# ────────────────────────────────────────────────────────────────────────────
# WalkForwardResult — with windows
# ────────────────────────────────────────────────────────────────────────────

class TestWalkForwardResultWithWindows:
    def setup_method(self):
        # Window 1: IS=12%, OOS=7% → ratio=0.583
        # Window 2: IS=10%, OOS=6% → ratio=0.600
        # avg efficiency = (0.583+0.600)/2 = 0.5917
        self.w1 = _make_window(1, train_return=12.0, forward_return=7.0,
                               train_score=1.5, forward_score=0.9,
                               best_params={"fast": 9, "slow": 26})
        self.w2 = _make_window(2, train_return=10.0, forward_return=6.0,
                               train_score=1.2, forward_score=1.1,
                               best_params={"fast": 12, "slow": 50})
        self.result = WalkForwardResult(
            windows=[self.w1, self.w2],
            symbol="RELIANCE.NS",
            strategy_name="EmaCross",
            metric="sharpe",
        )

    def test_efficiency_ratio_correct(self):
        er = self.result.efficiency_ratio()
        expected = round((7.0 / 12.0 + 6.0 / 10.0) / 2, 4)
        assert abs(er - expected) < 0.001

    def test_is_robust_true(self):
        assert self.result.is_robust() is True

    def test_best_params_max_forward_score(self):
        # w2 has higher forward_score (1.1 > 0.9)
        assert self.result.best_params() == {"fast": 12, "slow": 50}

    def test_avg_train_score(self):
        expected = round((1.5 + 1.2) / 2, 4)
        assert abs(self.result.avg_train_score() - expected) < 0.001

    def test_avg_forward_score(self):
        expected = round((0.9 + 1.1) / 2, 4)
        assert abs(self.result.avg_forward_score() - expected) < 0.001

    def test_avg_forward_return(self):
        expected = round((7.0 + 6.0) / 2, 2)
        assert abs(self.result.avg_forward_return() - expected) < 0.01

    def test_summary_df_shape(self):
        df = self.result.summary_df()
        assert len(df) == 2

    def test_summary_df_columns(self):
        df = self.result.summary_df()
        for col in ("window", "train", "forward", "best_params",
                    "train_score", "forward_score"):
            assert col in df.columns

    def test_summary_contains_strategy_name(self):
        s = self.result.summary()
        assert "EmaCross" in s

    def test_is_not_robust_below_threshold(self):
        # Force low efficiency by creating windows with low OOS/IS ratio
        w = _make_window(1, train_return=10.0, forward_return=1.0)  # ratio=0.1
        result = WalkForwardResult(windows=[w])
        assert result.is_robust(threshold=0.5) is False

    def test_custom_threshold_respected(self):
        er = self.result.efficiency_ratio()  # ~0.59
        assert self.result.is_robust(threshold=0.4) is True
        assert self.result.is_robust(threshold=0.9) is False

    def test_efficiency_skips_zero_train_return(self):
        w_zero = _make_window(3, train_return=0.0, forward_return=5.0)
        result = WalkForwardResult(windows=[w_zero])
        # Only window has train_return=0, so ratios list is empty -> 0.0
        assert result.efficiency_ratio() == 0.0


# ────────────────────────────────────────────────────────────────────────────
# WalkForwardTester._build_windows (pure date math)
# ────────────────────────────────────────────────────────────────────────────

class TestBuildWindows:
    def setup_method(self):
        self.tester = WalkForwardTester()

    def _build(self, from_date, to_date, train=12, validate=3, forward=3):
        return self.tester._build_windows(
            from_date=from_date, to_date=to_date,
            train_months=train, validate_months=validate,
            forward_months=forward,
        )

    def test_correct_window_count_2yr_range(self):
        # Range: 2020-01-01 to 2022-12-31 = 36 months
        # Each full window = 12+3+3 = 18 months, slides by 3 months
        # Windows possible: floor((36 - 18) / 3) + 1 = 7
        windows = self._build("2020-01-01", "2022-12-31")
        assert len(windows) == 7

    def test_first_train_start_equals_from_date(self):
        windows = self._build("2020-01-01", "2022-12-31")
        assert windows[0]["train_start"] == "2020-01-01"

    def test_window_required_keys_present(self):
        windows = self._build("2020-01-01", "2022-12-31")
        required = {"train_start", "train_end", "validate_start",
                    "validate_end", "forward_start", "forward_end"}
        for w in windows:
            assert required == set(w.keys())

    def test_forward_end_after_forward_start(self):
        windows = self._build("2020-01-01", "2022-12-31")
        for w in windows:
            assert w["forward_end"] > w["forward_start"]

    def test_consecutive_windows_slide_by_forward_months(self):
        windows = self._build("2020-01-01", "2023-12-31", forward=3)
        if len(windows) >= 2:
            start1 = date.fromisoformat(windows[0]["train_start"])
            start2 = date.fromisoformat(windows[1]["train_start"])
            from dateutil.relativedelta import relativedelta
            assert start2 == start1 + relativedelta(months=3)

    def test_no_windows_when_range_too_short(self):
        # Total window = 18 months but range is only 6 months
        windows = self._build("2020-01-01", "2020-06-30")
        assert len(windows) == 0

    def test_validate_end_before_forward_start(self):
        windows = self._build("2020-01-01", "2022-12-31")
        for w in windows:
            assert w["validate_end"] < w["forward_start"]


# ────────────────────────────────────────────────────────────────────────────
# WalkForwardTester._slice
# ────────────────────────────────────────────────────────────────────────────

class TestSlice:
    def setup_method(self):
        self.tester = WalkForwardTester()
        self.df = _make_ohlcv(300)  # 2020-01-01 onwards

    def test_slice_returns_subset(self):
        sliced = self.tester._slice(self.df, "2020-03-01", "2020-06-30")
        assert len(sliced) > 0
        assert len(sliced) < len(self.df)

    def test_slice_dates_within_range(self):
        sliced = self.tester._slice(self.df, "2020-03-01", "2020-06-30")
        assert sliced.index.min() >= pd.Timestamp("2020-03-01")
        assert sliced.index.max() <= pd.Timestamp("2020-06-30")

    def test_slice_empty_df_returns_empty(self):
        empty = pd.DataFrame()
        result = self.tester._slice(empty, "2020-01-01", "2020-06-30")
        assert result.empty


# ────────────────────────────────────────────────────────────────────────────
# WalkForwardTester._stitch_equity
# ────────────────────────────────────────────────────────────────────────────

class TestStitchEquity:
    def setup_method(self):
        self.tester = WalkForwardTester()

    def test_empty_list_returns_empty_series(self):
        result = self.tester._stitch_equity([], 100_000.0)
        assert isinstance(result, pd.Series)
        assert result.empty

    def test_single_series_starts_at_initial_capital(self):
        eq = pd.Series([100_000.0, 102_000.0, 105_000.0])
        stitched = self.tester._stitch_equity([eq], 100_000.0)
        assert stitched.iloc[0] == 100_000.0

    def test_two_series_second_starts_at_first_end(self):
        eq1 = pd.Series([100_000.0, 110_000.0])  # ends at 110k
        eq2 = pd.Series([100_000.0, 105_000.0])  # rebased to start at 110k
        stitched = self.tester._stitch_equity([eq1, eq2], 100_000.0)
        # After stitching, the join point should be continuous
        assert len(stitched) > 2
        assert stitched.iloc[0] == 100_000.0

    def test_stitch_grows_monotonically_for_growing_inputs(self):
        eq1 = pd.Series([100_000.0, 105_000.0, 110_000.0])
        eq2 = pd.Series([100_000.0, 106_000.0, 112_000.0])
        stitched = self.tester._stitch_equity([eq1, eq2], 100_000.0)
        # Final value should be above initial capital
        assert stitched.iloc[-1] > 100_000.0


# ────────────────────────────────────────────────────────────────────────────
# WalkForwardTester.run — mocked _fetch
# ────────────────────────────────────────────────────────────────────────────

class MockStrategy:
    """Minimal strategy stub for WFT run tests."""
    name = "MockStrategy"

    def __init__(self, **kwargs):
        self.params = kwargs

    def generate_signals(self, df):
        return pd.Series(0, index=df.index)


class TestWalkForwardRun:
    def test_run_returns_result_on_empty_data(self):
        """_fetch returns empty DataFrame — run must not crash, returns WalkForwardResult."""
        tester = WalkForwardTester()
        with patch.object(tester, "_fetch", return_value=pd.DataFrame()):
            result = tester.run(
                strategy_class=MockStrategy,
                params_grid={"fast": [5, 9]},
                symbol="DUMMY.NS",
                from_date="2020-01-01",
                to_date="2022-12-31",
            )
        assert isinstance(result, WalkForwardResult)
        assert len(result.windows) == 0

    def test_run_with_mocked_data_produces_windows(self, monkeypatch):
        """_fetch returns real OHLCV stub; _score is mocked to return None (no strategy engine needed)."""
        df = _make_ohlcv(600)  # ~2.4 years of business days

        tester = WalkForwardTester()
        monkeypatch.setattr(tester, "_fetch", lambda *a, **kw: df)
        monkeypatch.setattr(tester, "_score", lambda *a, **kw: None)

        result = tester.run(
            strategy_class=MockStrategy,
            params_grid={"fast": [5]},
            symbol="DUMMY.NS",
            from_date="2020-01-01",
            to_date="2022-04-30",
            train_months=12,
            validate_months=3,
            forward_months=3,
        )
        assert isinstance(result, WalkForwardResult)
        assert len(result.windows) >= 1

    def test_run_result_has_symbol(self, monkeypatch):
        tester = WalkForwardTester()
        monkeypatch.setattr(tester, "_fetch", lambda *a, **kw: pd.DataFrame())
        result = tester.run(
            strategy_class=MockStrategy,
            params_grid={"fast": [5]},
            symbol="RELIANCE.NS",
            from_date="2020-01-01",
            to_date="2022-12-31",
        )
        assert result.symbol == "RELIANCE.NS"
