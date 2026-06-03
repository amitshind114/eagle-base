"""Strategy plugin discovery.

Drop any strategy file that exports a class inheriting BaseStrategy
into this directory — it will be auto-discovered by the StrategyRegistry.

Example:
    strategies/plugins/my_custom_strategy.py
        class MyCustomStrategy(BaseStrategy):
            name = "my_custom"
            ...
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path


def discover_plugins() -> list[str]:
    """Return list of discovered plugin module names."""
    plugin_dir = Path(__file__).parent
    discovered: list[str] = []
    for _, module_name, _ in pkgutil.iter_modules([str(plugin_dir)]):
        full_name = f"strategies.plugins.{module_name}"
        try:
            importlib.import_module(full_name)
            discovered.append(full_name)
        except Exception as exc:  # noqa: BLE001
            print(f"[plugins] Failed to load {full_name}: {exc}")
    return discovered
