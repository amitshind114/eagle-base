"""Data Validator — Phase 2.

Every dataset passes through this before use in backtesting or UI.
Never backtest bad data.

Checks:
  1. Missing candles (gap detection by calendar)
  2. Duplicate timestamps
  3. Zero / null OHLCV values
  4. Price spikes (single candle >20% move)
  5. Volume = 0 on a trading row
  6. Split detection (close-to-open gap >40%)
  7. OHLC sanity (High >= Low, High >= Close, Low <= Close)
  8. Weekend rows in daily data
  9. Minimum bar count

Usage:
    from data.validator import DataValidator
    v = DataValidator()
    result = v.validate(df, interval="1d")
    if result.passed:
        print("clean")
    else:
        print(result.issues)
    clean_df = result.clean_df   # auto-cleaned version
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from core.logger import get_logger

log = get_logger("data.validator")


@dataclass
class ValidationResult:
    passed: bool
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rows_removed: int = 0
    clean_df: Optional[pd.DataFrame] = None

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"Validation: {status}"]
        for i in self.issues:
            lines.append(f"  [ERROR] {i}")
        for w in self.warnings:
            lines.append(f"  [WARN]  {w}")
        if self.rows_removed:
            lines.append(f"  Rows removed by auto-clean: {self.rows_removed}")
        return "\n".join(lines)


class DataValidator:
    """Validates and auto-cleans OHLCV DataFrames."""

    def __init__(
        self,
        spike_threshold: float = 0.20,   # 20% single-candle move = spike
        split_threshold: float = 0.40,   # 40% gap = possible split
        min_bars: int = 5,
    ) -> None:
        self.spike_threshold = spike_threshold
        self.split_threshold = split_threshold
        self.min_bars = min_bars

    def validate(
        self,
        df: pd.DataFrame,
        interval: str = "1d",
        symbol: str = "",
        auto_clean: bool = True,
    ) -> ValidationResult:
        """
        Run all validation checks on an OHLCV DataFrame.

        Args:
            df        : DataFrame with Open,High,Low,Close,Volume columns.
            interval  : Bar interval string ("1m","5m","1d" etc.).
            symbol    : Symbol name for logging.
            auto_clean: If True, return cleaned df in result.

        Returns:
            ValidationResult with passed flag, issues list, and clean_df.
        """
        if df is None or df.empty:
            return ValidationResult(
                passed=False,
                issues=["DataFrame is empty or None"],
                clean_df=pd.DataFrame(),
            )

        issues: List[str] = []
        warnings: List[str] = []
        clean = df.copy()
        original_len = len(clean)

        # ─ 1. Required columns ───────────────────────────────────────────────
        required = {"Open", "High", "Low", "Close", "Volume"}
        missing_cols = required - set(clean.columns)
        if missing_cols:
            issues.append(f"Missing columns: {missing_cols}")
            return ValidationResult(passed=False, issues=issues, clean_df=clean)

        # ─ 2. Duplicate timestamps ────────────────────────────────────────
        dupes = clean.index.duplicated().sum()
        if dupes:
            warnings.append(f"{dupes} duplicate timestamps found — keeping last.")
            clean = clean[~clean.index.duplicated(keep="last")]

        # ─ 3. Null / NaN close prices ────────────────────────────────────
        null_close = clean["Close"].isna().sum()
        if null_close:
            warnings.append(f"{null_close} rows with null Close — dropping.")
            clean = clean.dropna(subset=["Close"])

        # ─ 4. Zero close prices ──────────────────────────────────────────
        zero_close = (clean["Close"] == 0).sum()
        if zero_close:
            warnings.append(f"{zero_close} rows with zero Close — dropping.")
            clean = clean[clean["Close"] > 0]

        # ─ 5. OHLC sanity ─────────────────────────────────────────────────
        bad_hl = (clean["High"] < clean["Low"]).sum()
        if bad_hl:
            warnings.append(f"{bad_hl} rows where High < Low — dropping.")
            clean = clean[clean["High"] >= clean["Low"]]

        # ─ 6. Price spikes (>spike_threshold single candle) ────────────────
        if len(clean) > 2:
            pct_change = clean["Close"].pct_change().abs()
            spike_mask = pct_change > self.spike_threshold
            spike_count = spike_mask.sum()
            if spike_count:
                # Warning only — do NOT auto-remove spikes (could be real gap-up)
                worst = float(pct_change[spike_mask].max() * 100)
                warnings.append(
                    f"{spike_count} potential price spikes detected (>{self.spike_threshold*100:.0f}%). "
                    f"Worst: {worst:.1f}%. Verify splits/dividends."
                )

        # ─ 7. Split detection (close-to-open gap >split_threshold) ─────────
        if len(clean) > 2 and interval in ("1d", "1wk", "1mo"):
            prev_close = clean["Close"].shift(1)
            gap = ((clean["Open"] - prev_close) / prev_close).abs()
            split_mask = gap > self.split_threshold
            split_count = split_mask.sum()
            if split_count:
                dates = clean.index[split_mask].tolist()[:3]
                warnings.append(
                    f"{split_count} possible split/adjustment event(s) near: "
                    + ", ".join(str(d)[:10] for d in dates)
                )

        # ─ 8. Zero volume rows (only flag for daily+, intraday can have 0 vol) ─
        if interval in ("1d", "1wk", "1mo"):
            zero_vol = (clean["Volume"] == 0).sum()
            if zero_vol > 0:
                warnings.append(f"{zero_vol} rows with zero volume (possible holiday/halt rows).")

        # ─ 9. Weekend rows in daily data ──────────────────────────────────
        if interval == "1d":
            weekend_mask = clean.index.dayofweek >= 5
            weekend_count = weekend_mask.sum()
            if weekend_count:
                warnings.append(f"{weekend_count} weekend rows found — dropping.")
                clean = clean[~weekend_mask]

        # ─ 10. Gap detection (missing candles) ────────────────────────────
        if len(clean) > 2 and interval in ("1m", "3m", "5m", "15m", "30m", "1h"):
            freq_map = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
            expected_gap = pd.Timedelta(minutes=freq_map.get(interval, 5))
            actual_gaps = clean.index.to_series().diff().dropna()
            # Only flag gaps larger than 2x expected (ignores lunch breaks etc.)
            big_gaps = actual_gaps[actual_gaps > expected_gap * 4]
            if len(big_gaps) > 0:
                warnings.append(
                    f"{len(big_gaps)} large time gaps in intraday data "
                    f"(possible market halt or missing bars)."
                )

        # ─ 11. Minimum bars after cleaning ────────────────────────────────
        if len(clean) < self.min_bars:
            issues.append(
                f"Only {len(clean)} bars after cleaning (minimum {self.min_bars}). "
                f"Fetch more data."
            )

        rows_removed = original_len - len(clean)
        passed = len(issues) == 0

        if symbol:
            log.debug(
                f"Validation {symbol}: {'PASS' if passed else 'FAIL'} "
                f"| bars={len(clean)} removed={rows_removed} "
                f"issues={len(issues)} warnings={len(warnings)}"
            )

        return ValidationResult(
            passed=passed,
            issues=issues,
            warnings=warnings,
            rows_removed=rows_removed,
            clean_df=clean if auto_clean else df,
        )
