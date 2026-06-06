"""WalkForwardResult — Phase 6.

Aggregates per-window WalkForward results into a single report.
Key metric: efficiency_ratio = OOS return / IS return.
  - ratio > 0.5 → strategy is robust (OOS captures most of IS edge)
  - ratio < 0.5 → possible curve-fitting (IS >> OOS)
  - ratio < 0   → strategy reverses out-of-sample (strongly overfitted)

Usage:
    from backtesting.wf_result import WalkForwardResult, WFWindow
    result = WalkForwardResult(windows=[w1, w2, w3])
    print(result.summary_df())
    print(result.efficiency_ratio())
    print(result.is_robust())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class WFWindow:
    """Results for a single walk-forward window.

    Attributes:
        window_id     : 1-based window index.
        train_start   : Training period start date string.
        train_end     : Training period end date string.
        validate_start: Validation period start date string.
        validate_end  : Validation period end date string.
        forward_start : Forward (OOS) period start date string.
        forward_end   : Forward (OOS) period end date string.
        best_params   : Params selected from training (grid/random search).
        train_score   : In-sample metric score (e.g. Sharpe on train window).
        validate_score: Score on validation window (used for early stopping).
        forward_score : Out-of-sample score on the unseen forward window.
        train_return  : In-sample total return %.
        forward_return: Out-of-sample total return %.
        forward_equity: Equity curve Series for the OOS forward period.
    """
    window_id:      int
    train_start:    str
    train_end:      str
    validate_start: str
    validate_end:   str
    forward_start:  str
    forward_end:    str
    best_params:    dict          = field(default_factory=dict)
    train_score:    float         = 0.0
    validate_score: float         = 0.0
    forward_score:  float         = 0.0
    train_return:   float         = 0.0   # %
    forward_return: float         = 0.0   # %
    forward_equity: pd.Series     = field(default_factory=pd.Series)

    def to_dict(self) -> dict:
        return {
            "window":         self.window_id,
            "train":          f"{self.train_start} → {self.train_end}",
            "forward":        f"{self.forward_start} → {self.forward_end}",
            "best_params":    str(self.best_params),
            "train_score":    round(self.train_score,    4),
            "validate_score": round(self.validate_score, 4),
            "forward_score":  round(self.forward_score,  4),
            "train_ret%":     round(self.train_return,   2),
            "forward_ret%":   round(self.forward_return, 2),
        }


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward analysis result.

    Attributes:
        windows                 : List of per-window results.
        combined_forward_equity : Stitched OOS equity curve across all windows.
        symbol                  : Symbol tested.
        strategy_name           : Strategy name.
        metric                  : Metric used for optimisation.
    """
    windows:                 list[WFWindow]   = field(default_factory=list)
    combined_forward_equity: pd.Series        = field(default_factory=pd.Series)
    symbol:                  str              = ""
    strategy_name:           str              = ""
    metric:                  str              = "sharpe"

    # ------------------------------------------------------------------
    # Key metrics
    # ------------------------------------------------------------------

    def efficiency_ratio(self) -> float:
        """OOS / IS return ratio averaged across all windows.

        Interpretation:
            > 0.5  → robust (OOS retains most of IS edge)
            0–0.5  → mild curve fitting
            < 0    → strategy reverses OOS (strong overfitting)
        """
        if not self.windows:
            return 0.0
        ratios = []
        for w in self.windows:
            if w.train_return != 0:
                ratios.append(w.forward_return / w.train_return)
        if not ratios:
            return 0.0
        return round(sum(ratios) / len(ratios), 4)

    def is_robust(self, threshold: float = 0.5) -> bool:
        """Return True if efficiency_ratio >= threshold."""
        return self.efficiency_ratio() >= threshold

    def best_params(self) -> dict:
        """Return params from the window with the highest forward score."""
        if not self.windows:
            return {}
        best = max(self.windows, key=lambda w: w.forward_score)
        return best.best_params

    def avg_train_score(self) -> float:
        if not self.windows:
            return 0.0
        return round(sum(w.train_score for w in self.windows) / len(self.windows), 4)

    def avg_forward_score(self) -> float:
        if not self.windows:
            return 0.0
        return round(sum(w.forward_score for w in self.windows) / len(self.windows), 4)

    def avg_forward_return(self) -> float:
        if not self.windows:
            return 0.0
        return round(sum(w.forward_return for w in self.windows) / len(self.windows), 2)

    # ------------------------------------------------------------------
    # DataFrames
    # ------------------------------------------------------------------

    def summary_df(self) -> pd.DataFrame:
        """Return a per-window summary DataFrame."""
        if not self.windows:
            return pd.DataFrame()
        return pd.DataFrame([w.to_dict() for w in self.windows])

    # ------------------------------------------------------------------
    # Text summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        er = self.efficiency_ratio()
        robust_label = "✅ ROBUST" if self.is_robust() else "⚠️  CURVE-FITTED"
        lines = [
            f"{'='*65}",
            f"  Walk Forward: {self.strategy_name} on {self.symbol}",
            f"  Metric: {self.metric}  |  Windows: {len(self.windows)}",
            f"{'='*65}",
            f"  Avg IS  score    : {self.avg_train_score()}",
            f"  Avg OOS score    : {self.avg_forward_score()}",
            f"  Avg OOS return   : {self.avg_forward_return():.2f}%",
            f"  Efficiency Ratio : {er:.4f}  →  {robust_label}",
            f"  Best Params      : {self.best_params()}",
            f"{'='*65}",
        ]
        for w in self.windows:
            lines.append(
                f"  Win {w.window_id}: IS={w.train_score:.3f} "
                f"VAL={w.validate_score:.3f} OOS={w.forward_score:.3f} "
                f"| IS ret={w.train_return:+.1f}% OOS ret={w.forward_return:+.1f}% "
                f"| params={w.best_params}"
            )
        lines.append(f"{'='*65}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"<WalkForwardResult strategy='{self.strategy_name}' "
            f"windows={len(self.windows)} "
            f"efficiency={self.efficiency_ratio():.2f} "
            f"robust={self.is_robust()}>"
        )
