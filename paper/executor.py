"""PaperExecutor — Phase 8 Paper Trading.

Single entry point for executing signals through the paper trading engine.
Simulates market impact and slippage before routing to PaperPortfolio.

Signal flow:
  Signal → RiskCheck → Slippage → MarketImpact → Portfolio.on_signal → ExecutionResult

Usage:
    executor = PaperExecutor(portfolio)
    result = executor.execute(
        signal="BUY",
        symbol="RELIANCE",
        price=2500.0,
        qty=10,
        avg_volume=1_000_000,
    )
    print(result.success, result.exec_price, result.order_id)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.logger import get_logger
from paper.portfolio import PaperPortfolio

log = get_logger("paper.executor")

# Default slippage and impact constants
_DEFAULT_SLIPPAGE_BPS = 5    # 0.05% per side
_IMPACT_PARTICIPATION  = 0.1  # assume 10% of volume participation


@dataclass
class ExecutionResult:
    success:    bool
    order_id:   Optional[str]
    symbol:     str
    signal:     str
    quantity:   int
    req_price:  float          # price requested
    exec_price: float          # price after slippage + impact
    slippage:   float          # absolute slippage amount
    impact:     float          # absolute market impact amount
    reason:     str = ""       # rejection reason if success=False

    @property
    def total_cost(self) -> float:
        return self.exec_price * self.quantity


class PaperExecutor:
    """Executes signals with realistic slippage and market impact simulation.

    Args:
        portfolio         : PaperPortfolio instance to route orders to.
        slippage_bps      : One-way slippage in basis points (default 5 = 0.05%).
        impact_participation: Fraction of avg_volume this order participates in
                              for impact calculation (default 0.10).
    """

    def __init__(
        self,
        portfolio: PaperPortfolio,
        slippage_bps: float = _DEFAULT_SLIPPAGE_BPS,
        impact_participation: float = _IMPACT_PARTICIPATION,
    ) -> None:
        self.portfolio            = portfolio
        self.slippage_bps         = slippage_bps
        self.impact_participation = impact_participation

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        signal: str,           # "BUY" | "SELL"
        symbol: str,
        price: float,
        qty: int,
        avg_volume: int = 0,   # optional — used for impact calculation
    ) -> ExecutionResult:
        """Execute a signal end-to-end through the paper engine.

        Args:
            signal     : "BUY" or "SELL".
            symbol     : Instrument symbol.
            price      : Last known market price.
            qty        : Number of shares / units.
            avg_volume : Average daily volume (for market impact). Pass 0 to skip.

        Returns:
            ExecutionResult with success flag, exec_price, slippage, impact.
        """
        side_up = signal.upper()
        if side_up not in ("BUY", "SELL"):
            return ExecutionResult(
                success=False, order_id=None, symbol=symbol,
                signal=signal, quantity=qty, req_price=price,
                exec_price=price, slippage=0.0, impact=0.0,
                reason=f"Invalid signal '{signal}'",
            )

        slippage = self.simulate_slippage(price, side_up)
        impact   = self.simulate_impact(qty, avg_volume) if avg_volume > 0 else 0.0

        direction = 1.0 if side_up == "BUY" else -1.0
        exec_price = round(price + direction * (slippage + impact), 2)

        log.debug(
            f"[executor] {side_up} {symbol} x{qty} "
            f"req={price:.2f} slip={slippage:.4f} impact={impact:.4f} "
            f"exec={exec_price:.2f}"
        )

        # Route to portfolio (portfolio handles its own risk check)
        order_id = self.portfolio.on_signal(
            signal=side_up,
            symbol=symbol,
            price=exec_price,
            qty=qty,
            slippage_pct=0.0,   # slippage already baked into exec_price
        )

        if order_id is None:
            return ExecutionResult(
                success=False, order_id=None, symbol=symbol,
                signal=signal, quantity=qty, req_price=price,
                exec_price=exec_price, slippage=slippage, impact=impact,
                reason="Portfolio rejected order (risk check failed)",
            )

        return ExecutionResult(
            success=True, order_id=order_id, symbol=symbol,
            signal=signal, quantity=qty, req_price=price,
            exec_price=exec_price, slippage=slippage, impact=impact,
        )

    # ------------------------------------------------------------------
    # Simulation helpers
    # ------------------------------------------------------------------

    def simulate_slippage(self, price: float, side: str) -> float:
        """Compute absolute slippage for a given price.

        Args:
            price: Market price.
            side : 'BUY' or 'SELL'.

        Returns:
            Absolute slippage amount (always positive; direction handled by caller).
        """
        slippage_pct = self.slippage_bps / 10_000.0
        return round(price * slippage_pct, 4)

    def simulate_impact(
        self, qty: int, avg_volume: int
    ) -> float:
        """Estimate market impact using a simple square-root model.

        Impact(bps) = participation_rate × sqrt(qty / avg_volume) × 10_000
        Capped at 50 bps to avoid unrealistic values.

        Args:
            qty        : Order size.
            avg_volume : Average daily volume.

        Returns:
            Impact as an absolute price amount (same units as price).
        """
        if avg_volume <= 0:
            return 0.0
        import math
        participation = qty / avg_volume
        impact_bps = self.impact_participation * math.sqrt(participation) * 10_000
        impact_bps = min(impact_bps, 50.0)  # cap at 50 bps
        # Return as fraction of price (caller multiplies by price)
        # Here we return the raw bps factor; caller scales
        return round(impact_bps / 10_000.0, 6)

    def __repr__(self) -> str:
        return (
            f"<PaperExecutor slippage={self.slippage_bps}bps "
            f"portfolio={self.portfolio}>"
        )
