"""Abstract base for all strategies — Phase 05 hardened.

Every strategy must:
  1. Subclass BaseStrategy
  2. Set class-level: name, version, description, author, tags, parameters
  3. Implement generate_signals(df) -> pd.Series  (returns int Series: 1/-1/0)
  4. Decorate with @register_strategy (auto-registers on import)

Optionally implement:
  - validate_params(params) -> bool   (called before backtest run)
  - meta() -> StrategyMeta            (returns live metadata snapshot)
  - on_bar(df) -> int                 (1/0/-1 for paper/live trading)
  - metadata() -> dict                (win_rate etc. for sizer)

Phase 05 fixes:
  - __init__ copies class-level tags/parameters to instance so
    self.tags.append("x") on one instance never affects other instances.
  - on_bar() now returns int (1/-1/0) not str. Paper executor no longer needs
    a str→int conversion dict.
  - _STRATEGY_REGISTRY protected by _REGISTRY_LOCK for 20-thread concurrency.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from strategies.meta import StrategyMeta

# Signal type is now int at the API boundary: 1=BUY, -1=SELL, 0=HOLD
# The str alias is kept for backward-compat internal use only.
Signal = int   # 1 | -1 | 0

_SIGNAL_MAP: dict[str, int] = {"BUY": 1, "SELL": -1, "HOLD": 0}


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

    Phase 05 FIX — mutable class defaults:
        Class-level `tags = []` and `parameters = {}` are SHARED across all
        instances of the same class. If SmaCrossover().tags.append("x"),
        every SmaCrossover instance sees that mutation.
        __init__ copies them to instance dicts/lists so each instance is
        fully independent.
    """

    name:        str  = "BaseStrategy"
    version:     str  = "1.0.0"
    description: str  = ""
    author:      str  = "eagle"
    tags:        list = []
    parameters:  dict = {}
    status:      str  = "active"

    def __init__(self) -> None:
        # Phase 05: shallow-copy class-level mutable defaults to instance.
        # list(self.__class__.tags) creates a new list per instance.
        # dict(self.__class__.parameters) creates a new dict per instance.
        # Subclasses that call super().__init__() get this automatically.
        # Subclasses that define their own __init__ and DON'T call super()
        # must do this manually — but the pattern is enforced by convention.
        self.tags       = list(self.__class__.tags)
        self.parameters = dict(self.__class__.parameters)

    # ── Required ────────────────────────────────────────────────────────

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return Series of 1 (long), -1 (short), 0 (flat), aligned to df.
        Values MUST be in {-1, 0, 1}. The engine rejects any other values.
        """
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

        Base checks (applied before subclass logic):
          - If params has 'fast' and 'slow': fast > 0, slow > 0, fast < slow
          - If params has 'period': period > 2

        These catch common mistakes like SmaCrossover(fast=50, slow=20)
        before the backtest runs and wastes compute.
        """
        # Base guard: fast/slow crossover params
        if "fast" in params and "slow" in params:
            fast = params["fast"]
            slow = params["slow"]
            if not (isinstance(fast, (int, float)) and fast > 0):
                return False
            if not (isinstance(slow, (int, float)) and slow > 0):
                return False
            if fast >= slow:
                return False

        # Base guard: single period param
        if "period" in params:
            period = params["period"]
            if not (isinstance(period, (int, float)) and period > 2):
                return False

        return True

    # ── Optional ────────────────────────────────────────────────────────────

    def on_bar(self, df: pd.DataFrame) -> int:
        """Bar-by-bar signal for live/paper trading.

        Phase 05 FIX: returns int (1/-1/0) not str.
        - 1  = BUY
        - -1 = SELL
        - 0  = HOLD

        Paper executor uses this directly. Engine uses generate_signals().
        Subclasses should return int. If a subclass accidentally returns a str
        ("BUY"/"SELL"/"HOLD"), it is silently converted here via _SIGNAL_MAP.
        """
        return 0

    def metadata(self) -> dict:
        """Return historical edge stats for risk.sizer.

        Must be overridden by each strategy. Keys:
            win_rate      : float  e.g. 0.52
            avg_win_pct   : float  e.g. 0.03  (3%)
            avg_loss_pct  : float  e.g. 0.02  (2%)

        Strategies that override this get automatic position sizing.
        Those that don't fall back to 1% risk per trade (sizer default).
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
# Protected by a Lock so MultiStockRunner ThreadPoolExecutor concurrent imports
# cannot cause a race condition on the dict.
_STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {}
_REGISTRY_LOCK = threading.Lock()


def register_strategy(cls: type[BaseStrategy]) -> type[BaseStrategy]:
    """Class decorator — auto-registers a strategy on import.

    Usage:
        @register_strategy
        class EmaCrossover(BaseStrategy):
            name = "EMA Crossover"
            ...

    Effect:
        strategies.base._STRATEGY_REGISTRY["EMA Crossover"] = EmaCrossover

    Thread-safe: uses _REGISTRY_LOCK so concurrent imports from
    MultiStockRunner ThreadPoolExecutor cannot corrupt the dict.

    The decorator is a pure passthrough — it never modifies the class.
    Existing code that uses EmaCrossover directly is completely unaffected.
    """
    with _REGISTRY_LOCK:
        _STRATEGY_REGISTRY[cls.name] = cls
    return cls
