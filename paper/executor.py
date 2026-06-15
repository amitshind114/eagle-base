"""PaperExecutor — Phase 6 Paper Trading.

Single entry point for executing signals through the paper trading engine.
Simulates market impact and slippage before routing to PaperPortfolio.

Signal flow:
  Signal → PriceResolution → RiskGate (via Portfolio) → Slippage
  → MarketImpact → Portfolio.on_signal → ExecutionResult

Price resolution order:
  1. Caller-supplied price > 0  → used as-is
  2. price=0.0 + fetcher available → auto-fetch live price
  3. price=0.0 + no fetcher        → ExecutionResult(success=False)

This prevents silent ₹0 executions that corrupt position avg_cost.

Usage:
    executor = PaperExecutor(portfolio, fetcher=data_fetcher)
    result = executor.execute("BUY", "RELIANCE", price=2500.0, qty=10)
    result = executor.execute("BUY", "RELIANCE", qty=10, live_price=True)
    result = executor.execute("BUY", "RELIANCE", qty=10)  # auto-fetches if fetcher set
    print(result.success, result.exec_price, result.order_id)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from paper.portfolio import PaperPortfolio

log = logging.getLogger("paper.executor")

_DEFAULT_SLIPPAGE_BPS = 5    # 0.05% per side
_IMPACT_PARTICIPATION  = 0.1  # 10% volume participation


@dataclass
class ExecutionResult:
    success:    bool
    order_id:   Optional[str]
    symbol:     str
    signal:     str
    quantity:   int
    req_price:  float
    exec_price: float
    slippage:   float
    impact:     float
    reason:     str = ""

    @property
    def total_cost(self) -> float:
        return self.exec_price * self.quantity


class PaperExecutor:
    """Executes signals with realistic slippage + market impact simulation.

    Args:
        portfolio            : PaperPortfolio instance.
        fetcher              : Optional DataFetcher used for live price resolution.
        slippage_bps         : One-way slippage in basis points (default 5).
        impact_participation : Fraction of avg_volume for impact calc (default 0.10).
    """

    def __init__(
        self,
        portfolio: PaperPortfolio,
        fetcher=None,
        slippage_bps: float = _DEFAULT_SLIPPAGE_BPS,
        impact_participation: float = _IMPACT_PARTICIPATION,
    ) -> None:
        self.portfolio            = portfolio
        self._fetcher             = fetcher
        self.slippage_bps         = slippage_bps
        self.impact_participation = impact_participation

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        signal: str,
        symbol: str,
        price: float = 0.0,
        qty: int = 1,
        avg_volume: int = 0,
        live_price: bool = False,
    ) -> ExecutionResult:
        """Execute a signal through the paper engine.

        Args:
            signal      : "BUY" or "SELL".
            symbol      : Instrument symbol (e.g. "RELIANCE.NS").
            price       : Market price.  If 0.0 and fetcher is available,
                          a live price is fetched automatically.
            qty         : Number of shares.
            avg_volume  : Average daily volume for impact calc. 0 = skip.
            live_price  : If True, forces a live fetch even when price > 0.

        Returns:
            ExecutionResult.
        """
        side_up = signal.upper()
        if side_up not in ("BUY", "SELL"):
            return ExecutionResult(
                success=False, order_id=None, symbol=symbol,
                signal=signal, quantity=qty, req_price=price,
                exec_price=price, slippage=0.0, impact=0.0,
                reason=f"Invalid signal '{signal}'",
            )

        # --- Price resolution ---
        resolved_price, err = self._resolve_price(symbol, price, live_price)
        if err:
            return ExecutionResult(
                success=False, order_id=None, symbol=symbol,
                signal=signal, quantity=qty, req_price=price,
                exec_price=0.0, slippage=0.0, impact=0.0,
                reason=err,
            )
        price = resolved_price

        slippage = self.simulate_slippage(price, side_up)
        impact   = self.simulate_impact(qty, avg_volume) if avg_volume > 0 else 0.0

        direction  = 1.0 if side_up == "BUY" else -1.0
        exec_price = round(price + direction * (slippage + impact), 2)

        log.debug(
            "[executor] %s %s x%d req=%.2f slip=%.4f impact=%.4f exec=%.2f",
            side_up, symbol, qty, price, slippage, impact, exec_price,
        )

        order_id = self.portfolio.on_signal(
            signal=side_up,
            symbol=symbol,
            price=exec_price,
            qty=qty,
            slippage_pct=0.0,
        )

        if order_id is None:
            return ExecutionResult(
                success=False, order_id=None, symbol=symbol,
                signal=signal, quantity=qty, req_price=price,
                exec_price=exec_price, slippage=slippage, impact=impact,
                reason="Portfolio rejected order (risk gate, cash check, or corruption guard)",
            )

        return ExecutionResult(
            success=True, order_id=order_id, symbol=symbol,
            signal=signal, quantity=qty, req_price=price,
            exec_price=exec_price, slippage=slippage, impact=impact,
        )

    # ------------------------------------------------------------------
    # Price resolution
    # ------------------------------------------------------------------

    def _resolve_price(self, symbol: str, price: float, force_live: bool) -> tuple[float, str]:
        """Resolve the execution price.

        Returns (price, error_string).  error_string is empty on success.
        """
        # Explicit live fetch requested
        if force_live:
            return self._fetch_live(symbol, price)

        # Caller supplied a valid price — use it
        if price > 0:
            return price, ""

        # price=0.0 — auto-fetch if fetcher is available
        if self._fetcher is not None:
            log.debug("[executor] price=0 for %s — auto-fetching live price", symbol)
            return self._fetch_live(symbol, price)

        # No price, no fetcher — hard failure
        return 0.0, (
            f"price=0.0 for {symbol} and no fetcher configured on PaperExecutor. "
            "Pass price > 0 or inject a DataFetcher."
        )

    def _fetch_live(self, symbol: str, fallback: float) -> tuple[float, str]:
        """Fetch live price from self._fetcher.  Returns (price, error)."""
        if self._fetcher is None:
            return 0.0, "live_price=True but no fetcher configured on PaperExecutor"
        try:
            fetched = self._fetcher.fetch_latest_price(symbol)
            if not fetched or fetched <= 0:
                return 0.0, f"Fetcher returned invalid price {fetched} for {symbol}"
            log.debug("[executor] live price %s = %.2f", symbol, fetched)
            return fetched, ""
        except Exception as exc:
            return 0.0, f"live_price fetch error for {symbol}: {exc}"

    # ------------------------------------------------------------------
    # Simulation helpers
    # ------------------------------------------------------------------

    def simulate_slippage(self, price: float, side: str) -> float:
        slippage_pct = self.slippage_bps / 10_000.0
        return round(price * slippage_pct, 4)

    def simulate_impact(self, qty: int, avg_volume: int) -> float:
        if avg_volume <= 0:
            return 0.0
        import math
        participation = qty / avg_volume
        impact_bps = self.impact_participation * math.sqrt(participation) * 10_000
        impact_bps = min(impact_bps, 50.0)
        return round(impact_bps / 10_000.0, 6)

    def __repr__(self) -> str:
        return (
            f"<PaperExecutor slippage={self.slippage_bps}bps "
            f"fetcher={'yes' if self._fetcher else 'no'} "
            f"portfolio={self.portfolio}>"
        )
