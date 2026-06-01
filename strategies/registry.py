"""Strategy Registry — Priority 4.

Auto-discovers and loads strategy plugins from strategies/plugins/.
Strategies are loaded as Python modules at runtime.

TODO (Phase 4 - Priority 4):
- Implement auto-discovery
- Implement validation (must inherit BaseStrategy)
- Implement registry CRUD
"""

from __future__ import annotations

from pathlib import Path

from core.logger import logger

PLUGINS_DIR = Path(__file__).parent / "plugins"
PLUGINS_DIR.mkdir(exist_ok=True)


class StrategyRegistry:
    """Manages discovery and loading of strategy plugins."""

    def __init__(self):
        self._strategies: dict = {}

    def discover(self) -> list[str]:
        """Discover all .py files in strategies/plugins/. TODO: Phase 4 Priority 4."""
        logger.info("Discovering strategies...")
        raise NotImplementedError("TODO: Phase 4 Priority 4")

    def load(self, name: str):
        """Load a strategy by name. TODO: Phase 4 Priority 4."""
        raise NotImplementedError("TODO: Phase 4 Priority 4")

    def list_all(self) -> list[str]:
        """Return list of all registered strategy names."""
        return list(self._strategies.keys())
