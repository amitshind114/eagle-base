"""Pre-trade risk gate — deterministic, zero external calls.

Every order request passes through `compute_allowed_actions()` before
being submitted to the broker.  Returns a structured AllowedAction that
describes exactly what is permitted, why, and at what size.

Checks (in order):
    1. Daily loss cap / trade count  (via risk.limits)
    2. Earnings proximity            (optional upcoming_events dict)
    3. Position concentration        (10% of capital hard cap)
    4. Cash sufficiency              (can we afford ≥ 1 share?)
    5. VIX regime                    (optional; India VIX)

The caller inspects `allowed.allowed` — if False, abort the order and
log `allowed.block_reason`.  If True, use `allowed.max_qty` as the
upper bound for position sizing.

Usage:
    from risk.gate import compute_allowed_actions

    allowed = compute_allowed_actions(
        symbol="RELIANCE",
        capital=200_000,
        prices={"RELIANCE": 2840.0},
        vix=18.5,
    )
    if not allowed.allowed:
        return err(allowed.block_reason)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Literal


@dataclass
class AllowedAction:
    """Pre-computed trade constraints for a symbol."""
    symbol:       str
    allowed:      bool
    direction:    Literal["BUY_ONLY", "SELL_ONLY", "BOTH", "NONE"]
    max_qty:      int
    max_capital:  float
    flags:        list[str]
    block_reason: str = ""
    warnings:     list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.allowed


def _get_risk_limits():
    from risk.limits import risk_limits
    return risk_limits


def _resolve_capital(capital: float | None) -> float:
    if capital is not None:
        return float(capital)
    return float(os.environ.get("TOTAL_CAPITAL", "200000"))


def _lookup_price(symbol: str, prices: dict | None) -> float | None:
    if not prices:
        return None
    return prices.get(symbol.upper()) or prices.get(symbol)


def _existing_position_value(symbol: str, portfolio: dict | None) -> float:
    if not portfolio:
        return 0.0
    pos = portfolio.get(symbol.upper()) or portfolio.get(symbol)
    if not pos:
        return 0.0
    qty   = float(pos.get("qty", 0))
    price = float(pos.get("current_price") or pos.get("avg_price", 0))
    return qty * price


def _days_to_event(symbol: str, upcoming_events: dict | None) -> int | None:
    if not upcoming_events:
        return None
    event_str = upcoming_events.get(symbol.upper()) or upcoming_events.get(symbol)
    if not event_str:
        return None
    try:
        delta = (date.fromisoformat(str(event_str)) - date.today()).days
        return max(delta, 0)
    except (ValueError, TypeError):
        return None


def _blocked(symbol: str, flags: list, warnings: list, reason: str) -> AllowedAction:
    return AllowedAction(
        symbol=symbol, allowed=False, direction="NONE",
        max_qty=0, max_capital=0.0, flags=flags,
        block_reason=reason, warnings=warnings,
    )


def compute_allowed_actions(
    symbol: str,
    exchange: str = "NSE",
    portfolio: dict | None = None,
    capital: float | None = None,
    prices: dict | None = None,
    upcoming_events: dict | None = None,
    vix: float | None = None,
) -> AllowedAction:
    """Return AllowedAction describing what is permitted for this symbol.

    All inputs are optional — the gate degrades gracefully when data is
    unavailable (no VIX? skip that check; no prices? estimate from capital).
    """
    sym            = symbol.upper()
    flags: list    = []
    warnings: list = []
    total_capital  = _resolve_capital(capital)

    if total_capital <= 0:
        return _blocked(sym, flags, warnings, "No capital available")

    rl = _get_risk_limits()
    try:
        rl.check(sym, "BUY", 1, 0.0)
    except Exception as exc:
        return _blocked(sym, flags, warnings, str(exc).splitlines()[0])

    position_limit  = total_capital * 0.10
    existing_value  = _existing_position_value(sym, portfolio)
    remaining_room  = position_limit - existing_value
    current_price   = _lookup_price(sym, prices)

    if current_price and current_price > 0:
        if remaining_room <= 0:
            flags.append("POSITION_LIMIT")
            base_max_qty = 0
        else:
            base_max_qty = int(remaining_room / current_price)
            if existing_value > 0:
                flags.append("POSITION_LIMIT")
    else:
        base_max_qty = int(position_limit / 100)

    max_qty     = base_max_qty
    max_capital = max(min(remaining_room, position_limit), 0.0)

    days = _days_to_event(sym, upcoming_events)
    if days is not None and days <= 3:
        flags.append("EARNINGS_PROXIMITY")
        warnings.append(f"Earnings in {days} day(s) — position halved")
        max_qty     = max(max_qty // 2, 0)
        max_capital = max_capital / 2.0

    if current_price and current_price > 0:
        if total_capital < current_price:
            return _blocked(sym, flags, warnings, "Insufficient capital — cannot afford 1 share")
        if total_capital < current_price * 5:
            flags.append("LOW_CASH")
            warnings.append("Low capital — fewer than 5 shares affordable")

    if vix is not None and vix > 20:
        flags.append("HIGH_VOLATILITY")
        warnings.append(f"India VIX {vix:.1f} — position halved")
        max_qty     = max(max_qty // 2, 0)
        max_capital = max_capital / 2.0

    direction: Literal["BUY_ONLY", "SELL_ONLY", "BOTH", "NONE"] = "BOTH" if max_qty > 0 else "NONE"

    return AllowedAction(
        symbol=sym, allowed=True, direction=direction,
        max_qty=max_qty, max_capital=max_capital,
        flags=flags, warnings=warnings,
    )
