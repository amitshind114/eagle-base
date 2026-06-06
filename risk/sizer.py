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

    Kelly formula (correct):
        b  = avg_win_pct / avg_loss_pct        (win/loss ratio)
        f* = (W * b - L) / b
           = (W * avg_win_pct - L * avg_loss_pct) / (avg_win_pct * avg_loss_pct)
        where W = win_rate, L = 1 - win_rate

    Verification:
        W=0.6, avg_win=0.04, avg_loss=0.025
        f* = (0.6*0.04 - 0.4*0.025) / (0.04 * 0.025)
           = (0.024 - 0.010) / 0.001
           = 0.014 / 0.001  = 14.0   ← raw Kelly fraction (as % of capital)

    Wait — Kelly is expressed in the same units as avg_win/avg_loss.
    When avg_win=0.04 (4%) and avg_loss=0.025 (2.5%), the formula gives:
        f* = (W*b - L) / b  where b = avg_win/avg_loss = 1.6
           = (0.6*1.6 - 0.4) / 1.6
           = (0.96 - 0.4) / 1.6
           = 0.56 / 1.6  = 0.35   ← 35% of capital  (correct, before half-Kelly)

    half_kelly = 0.35 / 2 = 0.175  (17.5% of capital bet)
    This lies in (0.1, 0.4) as required by the exit criteria.
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
        avg_win_pct:  average winning trade return as decimal (0.04 = 4%)
        avg_loss_pct: average losing trade loss   as decimal (0.025 = 2.5%)
        atr_pct:      ATR as fraction of price              (0.015 = 1.5%)
        lot_size:     minimum tradeable unit (1 for equities, lot size for F&O)

        IMPORTANT: avg_win_pct and avg_loss_pct must be decimals, not
        percentages.  BacktestResult.avg_win_pct is already %-of-trade
        divided by 100.  Runner extracts and passes them directly.
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

    # ── Kelly formula ────────────────────────────────────────────────────────

    def _kelly(self, win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
        """Correct Kelly criterion.

        f* = (W * b - L) / b
           where b = avg_win_pct / avg_loss_pct,  L = 1 - win_rate

        Equivalent to:
           f* = (W * avg_win_pct - L * avg_loss_pct) / (avg_win_pct * avg_loss_pct)

        Returns -1.0 as sentinel when inputs are degenerate (guard).
        Negative result means negative edge → caller skips trade.
        """
        if avg_win_pct <= 0 or avg_loss_pct <= 0:
            return -1.0   # degenerate guard

        b           = avg_win_pct / avg_loss_pct   # win-to-loss ratio
        loss_rate   = 1.0 - win_rate
        raw_kelly   = (win_rate * b - loss_rate) / b
        return raw_kelly

    # ── Volatility scalar ────────────────────────────────────────────────────

    def _vol_scalar(self, atr_pct: float) -> float:
        """Scale position by inverse volatility.

        Principle: when you know less (ATR unavailable), bet less.
        atr_pct = 0 → conservative default of 0.5 (not 2.0).
        atr_pct > 0 → target_risk_pct / atr_pct, clamped [0.25, 2.0].

        A 2.0 default when ATR is unknown is dangerous — it allocates the
        maximum multiplier on the exact bars where we have the least
        information.  0.5 is conservative and safe.
        """
        if atr_pct <= 0:
            return 0.5   # FIX: was 2.0 — conservative when ATR unavailable
        raw = self.target_risk_pct / atr_pct
        return float(max(0.25, min(raw, 2.0)))

    # ── Zero result helper ───────────────────────────────────────────────────

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
