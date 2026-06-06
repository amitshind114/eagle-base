"""Allocation methods for portfolio backtesting — Phase 5.

Determines how total_capital is split across a set of symbols
before each rebalance period.

Usage:
    from backtesting.allocation import AllocationMethod, allocate

    weights = allocate(
        method=AllocationMethod.EQUAL_WEIGHT,
        symbols=["RELIANCE.NS", "TCS.NS", "INFY.NS"],
        capital=300_000,
    )
    # → {"RELIANCE.NS": 100_000, "TCS.NS": 100_000, "INFY.NS": 100_000}
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd


class AllocationMethod(str, Enum):
    """Supported capital allocation strategies."""
    EQUAL_WEIGHT     = "equal_weight"
    RISK_PARITY      = "risk_parity"      # inverse-volatility weighting
    MOMENTUM_WEIGHT  = "momentum_weight"  # weight by recent return
    FIXED_FRACTIONAL = "fixed_fractional" # fixed % of capital per trade


def allocate(
    method: AllocationMethod,
    symbols: list[str],
    capital: float,
    returns: Optional[dict[str, pd.Series]] = None,  # symbol → return series
    fixed_pct: float = 0.10,                          # for FIXED_FRACTIONAL
    lookback: int    = 20,                            # bars for vol/momentum
) -> dict[str, float]:
    """Compute per-symbol capital allocation.

    Args:
        method      : AllocationMethod enum value.
        symbols     : Ordered list of symbols to allocate to.
        capital     : Total capital to distribute (float).
        returns     : Required for RISK_PARITY and MOMENTUM_WEIGHT.
                      Mapping symbol → pd.Series of daily returns.
        fixed_pct   : Fraction of capital per position (FIXED_FRACTIONAL only).
        lookback    : Number of recent bars to use for vol/momentum calc.

    Returns:
        dict symbol → allocated float capital.
        Symbols with zero/negative weight get 0.0 allocation.
    """
    if not symbols:
        return {}

    if method == AllocationMethod.EQUAL_WEIGHT:
        return _equal_weight(symbols, capital)

    if method == AllocationMethod.RISK_PARITY:
        return _risk_parity(symbols, capital, returns or {}, lookback)

    if method == AllocationMethod.MOMENTUM_WEIGHT:
        return _momentum_weight(symbols, capital, returns or {}, lookback)

    if method == AllocationMethod.FIXED_FRACTIONAL:
        return _fixed_fractional(symbols, capital, fixed_pct)

    raise ValueError(f"Unknown AllocationMethod: {method}")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _equal_weight(symbols: list[str], capital: float) -> dict[str, float]:
    """Split capital equally across all symbols."""
    per_symbol = capital / len(symbols)
    return {s: per_symbol for s in symbols}


def _risk_parity(
    symbols: list[str],
    capital: float,
    returns: dict[str, pd.Series],
    lookback: int,
) -> dict[str, float]:
    """Allocate inversely proportional to recent volatility.

    Symbols with missing return data fall back to equal weight.
    """
    vols: dict[str, float] = {}
    for s in symbols:
        r = returns.get(s)
        if r is not None and len(r) >= lookback:
            vol = float(r.iloc[-lookback:].std())
            vols[s] = vol if vol > 0 else 1e-6
        else:
            vols[s] = 1e-6  # treat as max-weight if no data

    inv_vols   = {s: 1.0 / v for s, v in vols.items()}
    total_inv  = sum(inv_vols.values())
    if total_inv == 0:
        return _equal_weight(symbols, capital)

    return {s: (inv_vols[s] / total_inv) * capital for s in symbols}


def _momentum_weight(
    symbols: list[str],
    capital: float,
    returns: dict[str, pd.Series],
    lookback: int,
) -> dict[str, float]:
    """Allocate proportionally to recent cumulative return (winners get more).

    Negative-momentum symbols get 0 allocation.
    """
    mom: dict[str, float] = {}
    for s in symbols:
        r = returns.get(s)
        if r is not None and len(r) >= lookback:
            cum = float((1 + r.iloc[-lookback:]).prod() - 1)
            mom[s] = max(cum, 0.0)  # clamp negatives to 0
        else:
            mom[s] = 0.0

    total_mom = sum(mom.values())
    if total_mom == 0:
        # All symbols have zero/negative momentum — fall back to equal weight
        return _equal_weight(symbols, capital)

    return {s: (mom[s] / total_mom) * capital for s in symbols}


def _fixed_fractional(
    symbols: list[str],
    capital: float,
    fixed_pct: float,
) -> dict[str, float]:
    """Allocate fixed_pct of total capital to each symbol.

    Total may exceed capital if many symbols are active — caller
    should enforce max_positions before calling.
    """
    per_symbol = capital * fixed_pct
    return {s: per_symbol for s in symbols}
