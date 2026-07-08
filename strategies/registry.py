"""Strategy registry — maps string IDs to strategy classes.

All strategies registered here are available for deployment via:
  - POST /api/live/deploy   (live trading)
  - POST /api/paper/signal  (paper trading)
  - POST /api/backtest/run  (backtesting)

To add a new strategy:
  1. Create ``strategies/<your_strategy>.py`` with a ``STRATEGY_ID`` class attr
  2. Import it in ``strategies/__init__.py``
  3. Register it below with ``register(YourStrategy)``

Usage::

    from strategies.registry import get_strategy_class, list_strategies

    cls = get_strategy_class("ema_cross")
    runner = cls(symbol="RELIANCE", capital=50000.0, params={})

    all_ids = list_strategies()   # ["ema_cross", "triple_ema", ...]
"""

from __future__ import annotations

from typing import Type

from core.logger import logger

# Internal registry dict: strategy_id -> class
_REGISTRY: dict[str, Type] = {}


def register(strategy_cls: Type) -> Type:
    """Register a strategy class. Can be used as a decorator or called directly.

    Args:
        strategy_cls: class with a ``STRATEGY_ID`` class attribute.

    Returns:
        The strategy class (unchanged) — allows use as a decorator.

    Raises:
        AttributeError: if the class has no ``STRATEGY_ID`` attribute.
        ValueError:     if the ``STRATEGY_ID`` is already registered.
    """
    sid = getattr(strategy_cls, "STRATEGY_ID", None)
    if not sid:
        raise AttributeError(
            f"{strategy_cls.__name__} must define a STRATEGY_ID class attribute."
        )
    if sid in _REGISTRY:
        raise ValueError(
            f"Strategy '{sid}' is already registered "
            f"(by {_REGISTRY[sid].__name__}). "
            f"Each strategy must have a unique STRATEGY_ID."
        )
    _REGISTRY[sid] = strategy_cls
    logger.debug(f"[registry] Registered strategy: '{sid}' → {strategy_cls.__name__}")
    return strategy_cls


def get_strategy_class(strategy_id: str) -> Type:
    """Return the strategy class for the given ID.

    Raises:
        KeyError: if strategy_id is not registered.
    """
    if strategy_id not in _REGISTRY:
        available = list(_REGISTRY.keys())
        raise KeyError(
            f"Strategy '{strategy_id}' not found in registry. "
            f"Available: {available}"
        )
    return _REGISTRY[strategy_id]


def list_strategies() -> list[str]:
    """Return sorted list of all registered strategy IDs."""
    return sorted(_REGISTRY.keys())


def strategy_info(strategy_id: str) -> dict:
    """Return metadata dict for a registered strategy."""
    cls = get_strategy_class(strategy_id)
    return {
        "id":          strategy_id,
        "class_name":  cls.__name__,
        "module":      cls.__module__,
        "doc":         (cls.__doc__ or "").strip().split("\n")[0],
    }


# ---------------------------------------------------------------------------
# Auto-register all built-in strategies
# ---------------------------------------------------------------------------

def _auto_register() -> None:
    """Register all strategies defined in the strategies package."""
    from strategies.ema_cross import EMACrossStrategy
    from strategies.triple_ema import TripleEMAStrategy

    register(EMACrossStrategy)
    register(TripleEMAStrategy)

    logger.info(
        f"[registry] Auto-registered {len(_REGISTRY)} strategy/ies: {list_strategies()}"
    )


_auto_register()
