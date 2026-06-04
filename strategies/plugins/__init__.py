"""Strategy plugin auto-discovery.

Any .py file placed in this folder is automatically discovered and
registered into the strategy registry. No manual imports needed.

Current plugins:
    orb   — Opening Range Breakout (intraday, NSE)
    vwap  — VWAP Mean-Reversion   (intraday, NSE)

To add a new strategy:
    1. Create strategies/plugins/my_strategy.py
    2. Define a class that inherits BaseStrategy
    3. It will be auto-loaded on next app start — nothing else needed.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from strategies.base import BaseStrategy

_PLUGIN_DIR = Path(__file__).parent
_registry: dict[str, type[BaseStrategy]] = {}


def _discover() -> None:
    """Walk the plugins directory and import every module."""
    for finder, module_name, _ispkg in pkgutil.iter_modules([str(_PLUGIN_DIR)]):
        full_name = f"strategies.plugins.{module_name}"
        try:
            mod = importlib.import_module(full_name)
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy
                ):
                    key = getattr(attr, "name", attr_name.lower())
                    _registry[key] = attr
        except Exception as exc:  # noqa: BLE001
            import warnings
            warnings.warn(f"[plugins] Failed to load {full_name}: {exc}", stacklevel=2)


_discover()


def get_plugin(name: str) -> type[BaseStrategy]:
    """Return a plugin strategy class by its registered name.

    Args:
        name: Strategy name as defined in the class attribute ``name``.

    Raises:
        KeyError: If no plugin with that name is registered.
    """
    if name not in _registry:
        raise KeyError(
            f"Plugin '{name}' not found. Available: {list(_registry.keys())}"
        )
    return _registry[name]


def list_plugins() -> list[str]:
    """Return sorted list of all registered plugin strategy names."""
    return sorted(_registry.keys())
