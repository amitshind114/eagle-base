"""RSI Strategy — backward-compatibility shim (Phase 7).

rsi_mean_reversion.py is now the canonical RSI implementation.
This file is kept ONLY so existing imports do not break:
    from strategies.rsi_strategy import RSIStrategy  ← still works

DO NOT add new logic here. Extend RsiMeanReversion instead.
"""

from __future__ import annotations

from strategies.rsi_mean_reversion import RsiMeanReversion

# Alias — RSIStrategy now IS RsiMeanReversion
RSIStrategy = RsiMeanReversion

__all__ = ["RSIStrategy"]
