"""Volatility-adjusted position sizer with half-Kelly and ATR normalisation.

Takes strategy edge metrics (win rate, avg win/loss) and current market
volatility (ATR as % of price) and returns an integer share/lot quantity
that keeps risk per trade at a target fraction of capital.

No external data fetches — caller supplies ATR and win-rate stats from
the strategy's own backtest history or live rolling window.

Usage:
    from risk.sizer import PositionSizer

    sizer  = PositionSizer(total_capital=200_000)
    result = sizer.size(
        symbol="INFY",
        price=1800.0,
        win_rate=0.58,
        avg_win_pct=0.04,
        avg_loss_pct=0.025,
        atr_pct=0.015,
    )
    qty = result.qty          # integer shares to buy
    print(result.rationale)   # human-readable breakdown
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SizeResult:
    """Output of PositionSizer.size()."""
    symbol:           str
    qty:              int
    position_value:   float
    position_pct:     float
    kelly_fraction:   float
    vol_scalar:       float
    rationale:        str


class PositionSizer:
    """Half-Kelly + ATR volatility-adjusted position sizer.

    Two-step approach:
        1. Half-Kelly sets the "edge fraction" — how much of capital the
           strategy's historical edge justifies risking.
        2. ATR scalar adjusts for current volatility — if the stock is
           moving twice as much as usual, size is halved.

    Both scalars are clamped so a single trade never exceeds
    `max_position_pct` of capital (default 10%).
    """

    def __init__(
        self,
        total_capital: float,
        max_position_pct: float = 0.10,
        target_risk_pct: float  = 0.01,
    ) -> None:
        """
        total_capital:    total trading capital in INR
        max_position_pct: hard cap per position (default 10% of capital)
        target_risk_pct:  target risk fraction per trade (default 1%)
        """
        if total_capital <= 0:
            raise ValueError("total_capital must be > 0")
        self.total_capital    = total_capital
        self.max_position_pct = max_position_pct
        self.target_risk_pct  = target_risk_pct

    def size(
        self,
        symbol: str,
        price: float,
        win_rate: float,
        avg_win_pct: float,
        avg_loss_pct: float,
        atr_pct: float,
        lot_size: int = 1,
    ) -> SizeResult:
        """Compute a volatility-adjusted position size.

        symbol:       trading symbol (for logging)
        price:        current market price per share/unit
        win_rate:     historical win rate (0–1)
        avg_win_pct:  average winning trade return (0.04 = 4%)
        avg_loss_pct: average losing trade loss   (0.025 = 2.5%)
        atr_pct:      ATR as fraction of price     (0.015 = 1.5%)
        lot_size:     minimum tradeable unit (1 for equities, lot size for F&O)
        """
        if price <= 0:
            return self._zero(symbol, "price must be > 0")

        raw_kelly  = self._kelly(win_rate, avg_win_pct, avg_loss_pct)
        half_kelly = max(raw_kelly / 2.0, 0.0)

        if half_kelly <= 0:
            return self._zero(
                symbol,
                f"Kelly={raw_kelly:.4f} — no statistical edge, skip trade",
                kelly_fraction=half_kelly,
            )

        vol_scalar = self._vol_scalar(atr_pct)
        final_pct  = min(half_kelly * vol_scalar, self.max_position_pct)
        final_pct  = max(final_pct, 0.0)

        raw_qty = math.floor(final_pct * self.total_capital / price)
        qty     = max((raw_qty // lot_size) * lot_size, 0)

        rationale = (
            f"Kelly(raw)={raw_kelly:.4f} half={half_kelly:.4f} "
            f"vol_scalar={vol_scalar:.3f}(atr={atr_pct:.4f}) "
            f"final={final_pct * 100:.2f}% "
            f"qty={qty}×lot{lot_size}@₹{price:.2f}"
        )

        return SizeResult(
            symbol=symbol,
            qty=qty,
            position_value=round(qty * price, 2),
            position_pct=final_pct,
            kelly_fraction=half_kelly,
            vol_scalar=vol_scalar,
            rationale=rationale,
        )

    def _kelly(self, win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
        if avg_win_pct <= 0 or avg_loss_pct <= 0:
            return -1.0
        return (win_rate / avg_loss_pct) - ((1.0 - win_rate) / avg_win_pct)

    def _vol_scalar(self, atr_pct: float) -> float:
        if atr_pct <= 0:
            return 2.0
        raw = self.target_risk_pct / atr_pct
        return float(max(0.25, min(raw, 2.0)))

    def _zero(
        self,
        symbol: str,
        rationale: str,
        kelly_fraction: float = 0.0,
    ) -> SizeResult:
        return SizeResult(
            symbol=symbol, qty=0, position_value=0.0,
            position_pct=0.0, kelly_fraction=kelly_fraction,
            vol_scalar=0.0, rationale=rationale,
        )
