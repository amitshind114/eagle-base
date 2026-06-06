"""Strategy Registry — Phase 7 complete.

Single source of truth for all registered strategies.
Strategies self-register via the @register_strategy decorator on import.
This registry reads from the module-level _STRATEGY_REGISTRY dict in base.py.

Usage:
    from strategies.registry import StrategyRegistry
    reg = StrategyRegistry()

    # Get all strategies
    reg.list_all()                     # → list[StrategyMeta]
    reg.list_by_tag("trend")           # → list[StrategyMeta]

    # Instantiate
    strategy = reg.get("EMA Crossover")           # default params
    strategy = reg.get("EMA Crossover", fast=9, slow=21)  # custom params

    # Results
    reg.update_result("EMA Crossover", result)    # store backtest result
    reg.get_latest_result("EMA Crossover")        # → BacktestResult | None
"""

from __future__ import annotations

from typing import Any, Optional, Type

from core.logger import get_logger
from strategies.base import BaseStrategy, _STRATEGY_REGISTRY
from strategies.meta import StrategyMeta

log = get_logger("strategies.registry")


class StrategyRegistry:
    """Registry for strategy classes — register once, instantiate anywhere.

    Strategies register themselves via @register_strategy on import.
    The registry triggers those imports in _load_defaults().
    """

    def __init__(self) -> None:
        self._results: dict[str, Any] = {}  # name → BacktestResult
        self._load_defaults()

    # ── Bootstrap ──────────────────────────────────────────────────────────

    def _load_defaults(self) -> None:
        """Import all built-in strategies so their @register_strategy fires."""
        import strategies.sma_crossover      # noqa: F401
        import strategies.ema_crossover      # noqa: F401
        import strategies.macd_signal        # noqa: F401
        import strategies.rsi_mean_reversion # noqa: F401
        log.info(
            f"[registry] Loaded {len(_STRATEGY_REGISTRY)} strategies: "
            f"{list(_STRATEGY_REGISTRY.keys())}"
        )

    # ── Registration ────────────────────────────────────────────────────────

    def register(self, strategy_class: Type[BaseStrategy]) -> None:
        """Manually register a strategy class (alternative to decorator)."""
        _STRATEGY_REGISTRY[strategy_class.name] = strategy_class
        log.debug(f"[registry] Manually registered: {strategy_class.name}")

    # ── Retrieval ───────────────────────────────────────────────────────────

    def get(self, name: str, **params) -> BaseStrategy:
        """Instantiate a registered strategy by name.

        Args:
            name   : Exact strategy name e.g. 'EMA Crossover', 'RSI Mean Reversion'
            **params: Override default parameters e.g. fast=9, slow=21

        Returns:
            Ready-to-use strategy instance.

        Raises:
            KeyError: Strategy name not registered.
        """
        cls = self._get_class(name)
        if params:
            if not cls().validate_params(params):
                raise ValueError(
                    f"Invalid params {params} for strategy '{name}'. "
                    f"Check validate_params() in the strategy class."
                )
            return cls(**params)
        return cls()

    def get_class(self, name: str) -> Type[BaseStrategy]:
        """Return the strategy class (not an instance) by name."""
        return self._get_class(name)

    def _get_class(self, name: str) -> Type[BaseStrategy]:
        if name not in _STRATEGY_REGISTRY:
            available = list(_STRATEGY_REGISTRY.keys())
            raise KeyError(
                f"Strategy '{name}' not found. "
                f"Available: {available}"
            )
        return _STRATEGY_REGISTRY[name]

    # ── Listing ─────────────────────────────────────────────────────────────

    def list_all(self) -> list[StrategyMeta]:
        """Return StrategyMeta for every registered strategy."""
        metas = []
        for name, cls in _STRATEGY_REGISTRY.items():
            try:
                m = cls().meta()
                if name in self._results:
                    m.last_result = self._results[name]
                metas.append(m)
            except Exception as exc:
                log.warning(f"[registry] meta() failed for {name}: {exc}")
        return metas

    def list_by_tag(self, tag: str) -> list[StrategyMeta]:
        """Return strategies whose tags list contains the given tag.

        Args:
            tag: e.g. 'trend', 'momentum', 'mean_reversion', 'intraday'
        """
        return [m for m in self.list_all() if tag in m.tags]

    def names(self) -> list[str]:
        """Return list of all registered strategy names."""
        return list(_STRATEGY_REGISTRY.keys())

    def count(self) -> int:
        return len(_STRATEGY_REGISTRY)

    # ── Results ─────────────────────────────────────────────────────────────

    def update_result(self, name: str, result: Any) -> None:
        """Store the latest BacktestResult for a strategy.

        Called automatically by MultiStockRunner and PortfolioEngine
        after each completed backtest.

        Args:
            name  : Strategy name matching strategy.name class attribute.
            result: Any BacktestResult-like object with a summary() method.
        """
        if name not in _STRATEGY_REGISTRY:
            log.warning(f"[registry] update_result: '{name}' is not registered.")
            return
        self._results[name] = result
        log.debug(f"[registry] Result updated for '{name}'")

    def get_latest_result(self, name: str) -> Optional[Any]:
        """Return the most recent BacktestResult for a strategy, or None."""
        return self._results.get(name)

    # ── Legacy compat ──────────────────────────────────────────────────────────

    def list_strategies(self) -> list[dict]:
        """Legacy alias — returns list of metadata dicts.

        Kept for backward compatibility with existing UI code.
        Prefer list_all() for new code.
        """
        return [m.to_dict() for m in self.list_all()]

    def list_names(self) -> list[str]:
        """Legacy alias for names()."""
        return self.names()
