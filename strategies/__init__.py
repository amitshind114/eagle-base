"""Eagle-Base strategies package.

All concrete strategy classes live here. Each must:
  1. Define a ``STRATEGY_ID`` class attribute (unique string key)
  2. Implement ``__init__(self, symbol, capital, params)``
  3. Implement ``on_bar(self, bar) -> dict | None``

Registration is handled by ``strategies/registry.py``.
Import strategies here so the registry auto-discovers them on import.
"""

from strategies.ema_cross import EMACrossStrategy
from strategies.triple_ema import TripleEMAStrategy

__all__ = [
    "EMACrossStrategy",
    "TripleEMAStrategy",
]
