"""Abstract base for all strategies — Phase 7 updated.

Every strategy must:
  1. Subclass BaseStrategy
  2. Set class-level: name, version, description, author, tags, parameters
  3. Implement generate_signals(df) -> pd.Series
  4. Decorate with @register_strategy (auto-registers on import)

Optionally implement:
  - validate_params(params) -> bool   (called before backtest run)
  - meta() -> StrategyMeta            (returns live metadata snapshot)
  - on_bar(df) -> Signal              (bar-by-bar live/paper trading)
  - metadata() -> dict                (legacy — win_rate etc. for sizer)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from strategies.meta import StrategyMeta

# Re-export Signal type alias so strategies can import from base
Signal = str   # "BUY" | "SELL" | "HOLD"


class BaseStrategy(ABC):
    """Abstract base strategy.

    Class-level attributes (set in each subclass):
        name        : str  — unique identifier e.g. "EMA Crossover"
        version     : str  — semver e.g. "1.1.0"
        description : str  — one-line summary
        author      : str  — creator  (default "eagle")
        tags        : list — e.g. ["trend", "daily"]
        parameters  : dict — default params e.g. {"fast": 12, "slow": 26}
        status      : str  — "active" | "testing" | "draft" | "retired"
    """

    name:        str  = "BaseStrategy"
    version:     str  = "1.0.0"
    description: str  = ""
    author:      str  = "eagle"
    tags:        list = []
    parameters:  dict = {}
    status:      str  = "active"

    # ── Required ────────────────────────────────────────────────────────

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return Series of 1 (long), -1 (short), 0 (flat), aligned to df."""
        ...

    # ── Phase 7: new required methods ────────────────────────────────────────

    def meta(self) -> StrategyMeta:
        """Return a live StrategyMeta snapshot for this instance.

        The registry stores and updates this after every backtest run.
        Override if your strategy needs a custom StrategyMeta.
        """
        return StrategyMeta(
            name=self.name,
            version=self.version,
            author=self.author,
            description=self.description,
            parameters=self.parameters,
            tags=list(self.tags),
            status=self.status,
        )

    def validate_params(self, params: dict[str, Any]) -> bool:
        """Return True if params are valid for this strategy.

        Called by StrategyRegistry before instantiating with custom params.
        Override to add strategy-specific validation.

        Default: always True (no validation).
        """
        return True

    # ── Optional ────────────────────────────────────────────────────────────

    def on_bar(self, df: pd.DataFrame) -> Signal:
        """Bar-by-bar signal for live/paper trading. Override in subclass."""
        return "HOLD"

    def metadata(self) -> dict:
        """Legacy: return historical edge stats for risk.sizer.

        Keys: win_rate, avg_win_pct, avg_loss_pct
        Strategies that override this get automatic position sizing.
        Those that don\'t fall back to 1% risk per trade.
        """
        return {}

    # ── ATR helper ────────────────────────────────────────────────────────────

    def atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """ATR as fraction of close. Falls back to TR-based if ai.indicators unavailable."""
        try:
            from ai.indicators import atr as _atr
            return _atr(df, period=period) / df["Close"]
        except Exception:
            high  = df["High"]
            low   = df["Low"]
            close = df["Close"]
            prev  = close.shift(1)
            tr    = pd.concat([
                high - low,
                (high - prev).abs(),
                (low  - prev).abs(),
            ], axis=1).max(axis=1)
            atr_series = tr.ewm(span=period, adjust=False).mean()
            return (atr_series / close.replace(0, float("nan"))).fillna(0)

    def sized_qty(
        self,
        price: float,
        df: pd.DataFrame,
        capital: float,
        lot_size: int = 1,
    ) -> int:
        """Position-sized quantity via risk.sizer."""
        from risk.sizer import PositionSizer
        m          = self.metadata()
        win_rate   = float(m.get("win_rate",     0.50))
        avg_win    = float(m.get("avg_win_pct",  0.02))
        avg_loss   = float(m.get("avg_loss_pct", 0.01))
        atr_pct    = float(self.atr(df).iloc[-1]) if not df.empty else 0.015
        sizer      = PositionSizer(total_capital=capital)
        result     = sizer.size(
            symbol=self.name, price=price,
            win_rate=win_rate, avg_win_pct=avg_win, avg_loss_pct=avg_loss,
            atr_pct=atr_pct,  lot_size=lot_size,
        )
        return result.qty

    def __repr__(self) -> str:
        return f"{self.name} v{self.version}"


# ── @register_strategy decorator ────────────────────────────────────────────────

# Module-level registry dict — populated by @register_strategy on import.
# StrategyRegistry reads from this at startup.
_STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register_strategy(cls: type[BaseStrategy]) -> type[BaseStrategy]:
    """Class decorator — auto-registers a strategy on import.

    Usage:
        @register_strategy
        class EmaCrossover(BaseStrategy):
            name = "EMA Crossover"
            ...

    Effect:
        strategies.base._STRATEGY_REGISTRY["EMA Crossover"] = EmaCrossover

    The decorator is a pure passthrough — it never modifies the class.
    Existing code that uses EmaCrossover directly is completely unaffected.
    """
    _STRATEGY_REGISTRY[cls.name] = cls
    return cls
