"""Multi-strategy runner with conflict resolution.

Runs N strategies concurrently on a shared symbol universe.
When two strategies disagree on the same symbol (BUY vs SELL),
the conflict is detected and the trade is skipped — no position is taken.

Usage:
    from backtesting.multi_runner import MultiStrategyRunner

    runner = MultiStrategyRunner(
        strategies=[sma_crossover, ema_crossover],
        symbols=["NIFTYBEES", "RELIANCE", "INFY", "TCS", "HDFCBANK"],
        executor=executor,
        session="live",
    )
    runner.run_once()   # evaluate all strategies on current bar

Conflict resolution rule (Phase 09 P2):
    If strategy_A signals BUY  and strategy_B signals SELL for the same symbol
    → skip the trade for that symbol this bar.
    If both agree (BUY+BUY or SELL+SELL) → proceed with whichever is first.
    If only one strategy has a view   → proceed normally.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.audit import audit
from core.logger import get_logger

log = get_logger("backtesting.multi_runner")


# ── Typing helpers ────────────────────────────────────────────────────────────

class Strategy(Protocol):
    """Minimal interface every strategy must satisfy."""
    name: str
    def generate_signal(self, symbol: str, bar: dict) -> str | None:
        """Return 'BUY', 'SELL', or None."""
        ...


@dataclass
class ConflictRecord:
    symbol:     str
    bar_ts:     str
    signals:    dict[str, str]   # {strategy_name: direction}
    resolution: str = "SKIP"     # always SKIP for now


# ── Runner ────────────────────────────────────────────────────────────────────

class MultiStrategyRunner:
    """Evaluate multiple strategies per bar; resolve direction conflicts.

    Args:
        strategies : list of strategy instances (must have .name + .generate_signal)
        symbols    : list of ticker strings to trade
        executor   : LiveExecutor or PaperBroker; must have .place_order()
        session    : "live" | "paper" — passed through to audit
        max_position_value : ₹ cap per symbol per trade (default 5_000)
    """

    def __init__(
        self,
        strategies: list[Strategy],
        symbols: list[str],
        executor: Any,
        session: str = "live",
        max_position_value: float = 5_000,
    ) -> None:
        self.strategies         = strategies
        self.symbols            = symbols
        self.executor           = executor
        self.session            = session
        self.max_position_value = max_position_value
        self.conflict_log: list[ConflictRecord] = []

    # ── Core method ───────────────────────────────────────────────────────────

    def run_once(self, bars: dict[str, dict]) -> dict[str, str | None]:
        """Evaluate all strategies on the current bar data.

        Args:
            bars: {symbol: bar_dict}  where bar_dict has at least 'ts', 'close'

        Returns:
            {symbol: action}  — 'BUY', 'SELL', 'SKIP_CONFLICT', or None
        """
        results: dict[str, str | None] = {}

        for symbol in self.symbols:
            bar = bars.get(symbol)
            if bar is None:
                results[symbol] = None
                continue

            # Collect one signal per strategy
            signals: dict[str, str] = {}
            for strat in self.strategies:
                try:
                    sig = strat.generate_signal(symbol, bar)
                    if sig in ("BUY", "SELL"):
                        signals[strat.name] = sig
                except Exception as exc:
                    log.warning(f"[multi_runner] {strat.name} error on {symbol}: {exc}")

            if not signals:
                results[symbol] = None
                continue

            directions = set(signals.values())

            # Conflict: two or more strategies disagree
            if len(directions) > 1:
                self._handle_conflict(symbol, bar, signals)
                results[symbol] = "SKIP_CONFLICT"
                continue

            # All strategies agree — use the consensus direction
            direction = directions.pop()
            results[symbol] = direction
            self._execute(symbol, direction, bar)

        return results

    # ── Conflict handler ──────────────────────────────────────────────────────

    def _handle_conflict(self, symbol: str, bar: dict,
                         signals: dict[str, str]) -> None:
        """Log and skip a conflicted symbol."""
        bar_ts = str(bar.get("ts", ""))
        rec = ConflictRecord(
            symbol=symbol,
            bar_ts=bar_ts,
            signals=signals,
            resolution="SKIP",
        )
        self.conflict_log.append(rec)
        log.info(
            f"[multi_runner] ⚡ CONFLICT skipped — {symbol} @ {bar_ts} "
            f"signals={signals}"
        )
        audit.record(
            "CONFLICT_SKIP",
            symbol,
            session=self.session,
            bar_ts=bar_ts,
            signals=signals,
            resolution="SKIP",
        )

    # ── Trade execution ───────────────────────────────────────────────────────

    def _execute(self, symbol: str, direction: str, bar: dict) -> None:
        """Place order via executor if position value cap allows."""
        ltp = float(bar.get("close", 0))
        if ltp <= 0:
            log.warning(f"[multi_runner] {symbol}: zero LTP — skipping order.")
            return

        qty = max(1, int(self.max_position_value // ltp))
        log.info(
            f"[multi_runner] → {direction} {qty}x {symbol} @ ₹{ltp:,.2f} "
            f"(pos_val≈₹{qty*ltp:,.0f})"
        )
        try:
            self.executor.place_order(
                symbol=symbol,
                side=direction,
                qty=qty,
                order_type="MARKET",
                session=self.session,
            )
        except Exception as exc:
            log.error(f"[multi_runner] place_order failed for {symbol}: {exc}")

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def conflict_summary(self) -> dict:
        """Return counts of conflicts per symbol since last reset."""
        summary: dict[str, int] = {}
        for rec in self.conflict_log:
            summary[rec.symbol] = summary.get(rec.symbol, 0) + 1
        return summary

    def reset_conflict_log(self) -> None:
        self.conflict_log.clear()
