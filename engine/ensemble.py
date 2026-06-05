"""Weighted signal ensemble — pure deterministic voting, no LLM.

Combines signals from multiple strategy instances using configurable
weights and a minimum consensus threshold.  A combined signal is only
emitted when the weighted vote clears `min_confidence` (default 0.55).

Below threshold the ensemble returns NEUTRAL (0) — the system does
nothing rather than act on weak agreement.

Usage:
    from engine.ensemble import SignalEnsemble
    from strategies.ema_crossover  import EMACrossoverStrategy
    from strategies.rsi_strategy   import RSIStrategy
    from strategies.macd_signal    import MACDSignalStrategy

    ensemble = SignalEnsemble([
        (EMACrossoverStrategy(),  0.4),
        (RSIStrategy(),           0.35),
        (MACDSignalStrategy(),    0.25),
    ])
    result = ensemble.vote(df)
    print(result.signal, result.confidence, result.breakdown)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from strategies.base import BaseStrategy


@dataclass(frozen=True)
class EnsembleResult:
    """Output of SignalEnsemble.vote()."""
    signal:     int            # 1 BUY | -1 SELL | 0 NEUTRAL
    confidence: float          # weighted vote score 0–1
    direction:  str            # "BUY" | "SELL" | "NEUTRAL"
    breakdown:  dict           # {strategy_name: (raw_signal, weight)}
    threshold:  float          # min_confidence used
    agreed:     bool           # True when confidence >= threshold


class SignalEnsemble:
    """Combine multiple strategies via weighted majority voting.

    Weights do not need to sum to 1 — they are normalised internally.
    Strategies with weight 0 are ignored.
    """

    def __init__(
        self,
        strategies: list[tuple["BaseStrategy", float]],
        min_confidence: float = 0.55,
    ) -> None:
        """
        strategies:     list of (strategy_instance, weight) tuples
        min_confidence: weighted vote fraction required to emit a signal
        """
        if not strategies:
            raise ValueError("At least one strategy required")
        self._strategies    = [(s, max(w, 0.0)) for s, w in strategies]
        self.min_confidence = min_confidence

    def vote(self, df: pd.DataFrame) -> EnsembleResult:
        """Run all strategies on df and return a combined EnsembleResult.

        Each strategy\'s last-bar signal is weighted and summed.
        The sign of the weighted sum determines direction;
        the magnitude (normalised to [0,1]) is the confidence score.

        Strategies that raise an exception contribute 0 to the vote
        — they do not crash the ensemble.
        """
        total_weight = sum(w for _, w in self._strategies)
        if total_weight == 0:
            return self._neutral({}, self.min_confidence)

        weighted_sum = 0.0
        breakdown    = {}

        for strategy, weight in self._strategies:
            if weight == 0:
                continue
            try:
                signals   = strategy.generate_signals(df)
                last_sig  = int(signals.iloc[-1]) if not signals.empty else 0
                last_sig  = max(-1, min(1, last_sig))   # clamp to [-1, 0, 1]
            except Exception:
                last_sig  = 0
            weighted_sum               += last_sig * weight
            breakdown[strategy.name]    = {"signal": last_sig, "weight": weight}

        normalised = weighted_sum / total_weight   # range [-1, 1]
        confidence = abs(normalised)               # 0–1, how strongly they agree

        if confidence < self.min_confidence or normalised == 0:
            return self._neutral(breakdown, self.min_confidence)

        signal    = 1 if normalised > 0 else -1
        direction = "BUY" if signal == 1 else "SELL"

        return EnsembleResult(
            signal=signal,
            confidence=round(confidence, 4),
            direction=direction,
            breakdown=breakdown,
            threshold=self.min_confidence,
            agreed=True,
        )

    def vote_series(self, df: pd.DataFrame) -> pd.Series:
        """Run ensemble bar-by-bar and return a signal Series aligned to df.

        Slower than vote() — use for backtesting ensemble strategies.
        Each bar uses only data up to that bar (no lookahead).
        """
        signals = []
        for i in range(len(df)):
            window = df.iloc[: i + 1]
            if len(window) < 5:
                signals.append(0)
                continue
            try:
                result = self.vote(window)
                signals.append(result.signal)
            except Exception:
                signals.append(0)
        return pd.Series(signals, index=df.index, name="ensemble_signal")

    def add(self, strategy: "BaseStrategy", weight: float) -> None:
        """Add a strategy to the ensemble at runtime."""
        self._strategies.append((strategy, max(weight, 0.0)))

    def remove(self, name: str) -> None:
        """Remove a strategy from the ensemble by name."""
        self._strategies = [(s, w) for s, w in self._strategies if s.name != name]

    def _neutral(self, breakdown: dict, threshold: float) -> EnsembleResult:
        return EnsembleResult(
            signal=0, confidence=0.0, direction="NEUTRAL",
            breakdown=breakdown, threshold=threshold, agreed=False,
        )
