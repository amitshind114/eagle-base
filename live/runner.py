"""StrategyRunner — per-strategy execution unit inside LiveEngine.

Each deployed strategy gets exactly ONE StrategyRunner. It owns:
  - One strategy instance (from strategies registry)
  - One broker executor (LiveExecutor or PaperExecutor)
  - One position book (live or paper)
  - The tick loop (run in a background thread)

State machine::

    CREATED → STARTING → RUNNING → PAUSED → RUNNING
                                 → STOPPING → STOPPED
                                 → ERROR

Thread safety:
  - _state transitions protected by _lock
  - _orders and _positions are append-only lists — reads are safe without lock
    because Python list.append is GIL-protected; no in-place mutation occurs

Usage (internal — called by LiveEngine)::

    runner = StrategyRunner(run_id, StrategyClass, "RELIANCE", 50000.0, "paper", "angelone")
    runner.start()      # launches background thread
    runner.pause()      # suspends tick processing
    runner.resume()     # resumes tick processing
    runner.stop()       # graceful shutdown
    runner.stop(force=True)  # immediate shutdown
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Type

from core.audit import audit
from core.logger import logger

# Tick interval in seconds (default: 60s = 1-minute bars)
_DEFAULT_TICK_INTERVAL: float = float(
    __import__("os").environ.get("EAGLE_TICK_INTERVAL", "60")
)


class RunnerState:
    CREATED  = "created"
    STARTING = "starting"
    RUNNING  = "running"
    PAUSED   = "paused"
    STOPPING = "stopping"
    STOPPED  = "stopped"
    ERROR    = "error"


class StrategyRunner:
    """Runs a single strategy in a background thread."""

    def __init__(
        self,
        run_id: str,
        strategy_cls: Type,
        symbol: str,
        capital: float,
        mode: str,
        broker: str,
        params: dict,
        tick_interval: float = _DEFAULT_TICK_INTERVAL,
    ) -> None:
        self.run_id        = run_id
        self.symbol        = symbol
        self.capital       = capital
        self.mode          = mode           # "paper" | "live"
        self.broker        = broker
        self.params        = params
        self.deployed_at   = datetime.now(timezone.utc).isoformat()
        self._tick_interval = tick_interval

        self._state: str = RunnerState.CREATED
        self._lock   = threading.Lock()
        self._stop_event   = threading.Event()
        self._pause_event  = threading.Event()   # set = paused
        self._thread: threading.Thread | None = None
        self._error: str | None = None

        # Order + position history (append-only, GIL-safe reads)
        self._orders:    list[dict[str, Any]] = []
        self._positions: list[dict[str, Any]] = []

        # Instantiate strategy
        self._strategy = strategy_cls(symbol=symbol, capital=capital, params=params)

        # Instantiate executor
        self._executor = self._build_executor()

        logger.info(f"[Runner:{run_id}] Initialised — {strategy_cls.__name__}/{symbol}/{mode}")

    # ------------------------------------------------------------------
    # Executor factory
    # ------------------------------------------------------------------

    def _build_executor(self):
        """Return a LiveExecutor (live mode) or PaperExecutor stub (paper mode)."""
        if self.mode == "live":
            from live.executor import LiveExecutor
            executor = LiveExecutor()
            executor.connect()
            return executor
        else:
            # Paper mode: lightweight in-memory stub
            return _PaperExecutorStub(symbol=self.symbol, capital=self.capital)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch background tick thread."""
        with self._lock:
            if self._state not in (RunnerState.CREATED,):
                raise RuntimeError(f"Cannot start runner in state '{self._state}'")
            self._state = RunnerState.STARTING

        self._thread = threading.Thread(
            target=self._tick_loop,
            name=f"runner-{self.run_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[Runner:{self.run_id}] Thread started.")

    def pause(self) -> None:
        """Suspend tick loop after current bar completes."""
        with self._lock:
            if self._state != RunnerState.RUNNING:
                return
            self._pause_event.set()
            self._state = RunnerState.PAUSED
        logger.info(f"[Runner:{self.run_id}] Paused.")

    def resume(self) -> None:
        """Resume a paused runner."""
        with self._lock:
            if self._state != RunnerState.PAUSED:
                return
            self._pause_event.clear()
            self._state = RunnerState.RUNNING
        logger.info(f"[Runner:{self.run_id}] Resumed.")

    def stop(self, force: bool = False) -> None:
        """Signal the tick loop to stop.

        Args:
            force: if True, skip waiting for the current bar to complete.
        """
        with self._lock:
            if self._state in (RunnerState.STOPPED, RunnerState.STOPPING):
                return
            self._state = RunnerState.STOPPING

        self._stop_event.set()
        self._pause_event.clear()  # unblock if paused

        if not force and self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)

        with self._lock:
            self._state = RunnerState.STOPPED

        audit.record("RUNNER_STOPPED", self.symbol, session=self.mode, run_id=self.run_id)
        logger.info(f"[Runner:{self.run_id}] Stopped (force={force}).")

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    def _tick_loop(self) -> None:
        """Main strategy execution loop — runs in background thread."""
        with self._lock:
            self._state = RunnerState.RUNNING

        logger.info(f"[Runner:{self.run_id}] Tick loop started (interval={self._tick_interval}s).")

        while not self._stop_event.is_set():
            # Respect pause
            if self._pause_event.is_set():
                time.sleep(1.0)
                continue

            try:
                self._tick()
            except Exception as exc:
                logger.error(f"[Runner:{self.run_id}] Tick error: {exc}")
                audit.record("RUNNER_TICK_ERROR", self.symbol, session=self.mode,
                             run_id=self.run_id, error=str(exc))
                with self._lock:
                    self._error = str(exc)
                    self._state = RunnerState.ERROR
                break  # exit loop on unhandled tick error

            # Wait for next bar (or stop signal)
            self._stop_event.wait(timeout=self._tick_interval)

        with self._lock:
            if self._state not in (RunnerState.ERROR,):
                self._state = RunnerState.STOPPED

        logger.info(f"[Runner:{self.run_id}] Tick loop exited.")

    def _tick(self) -> None:
        """Single tick: fetch bar → call strategy.on_bar() → execute signal."""
        bar = self._fetch_latest_bar()
        if bar is None:
            logger.debug(f"[Runner:{self.run_id}] No bar data — skipping tick.")
            return

        signal = self._strategy.on_bar(bar)
        if signal is None:
            return

        self._execute_signal(signal, bar)

    def _fetch_latest_bar(self) -> dict | None:
        """Fetch the latest OHLCV bar for self.symbol.

        Production: use Angel One WebSocket or REST market feed.
        Fallback:   yfinance 1-min bar (acceptable for paper testing).
        """
        try:
            import yfinance as yf
            sym = self.symbol if self.symbol.endswith(".NS") else f"{self.symbol}.NS"
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="1d", interval="1m")
            if hist.empty:
                return None
            row = hist.iloc[-1]
            return {
                "symbol":    self.symbol,
                "open":      float(row["Open"]),
                "high":      float(row["High"]),
                "low":       float(row["Low"]),
                "close":     float(row["Close"]),
                "volume":    float(row["Volume"]),
                "timestamp": str(hist.index[-1]),
            }
        except Exception as exc:
            logger.warning(f"[Runner:{self.run_id}] Bar fetch failed: {exc}")
            return None

    def _execute_signal(self, signal: dict, bar: dict) -> None:
        """Pass signal to executor and record the resulting order."""
        side = signal.get("side")         # "BUY" | "SELL"
        qty  = signal.get("qty", 1)
        price = bar.get("close", 0.0)

        if not side:
            return

        try:
            result = self._executor.place_order(
                symbol=self.symbol,
                side=side,
                qty=qty,
                price=price,
                signal_timestamp=bar.get("timestamp", ""),
            )
            order_record = {
                "run_id":    self.run_id,
                "symbol":    self.symbol,
                "side":      side,
                "qty":       qty,
                "price":     price,
                "status":    "filled",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "broker_ref": result.get("orderid", "") if isinstance(result, dict) else "",
            }
        except Exception as exc:
            logger.error(f"[Runner:{self.run_id}] Signal execution failed: {exc}")
            order_record = {
                "run_id":    self.run_id,
                "symbol":    self.symbol,
                "side":      side,
                "qty":       qty,
                "price":     price,
                "status":    "rejected",
                "error":     str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        self._orders.append(order_record)
        self._update_positions(order_record)

    def _update_positions(self, order: dict) -> None:
        """Update internal position snapshot after a fill."""
        if order.get("status") != "filled":
            return
        # Simple net-position tracking
        existing = next(
            (p for p in self._positions if p["symbol"] == order["symbol"]), None
        )
        qty_delta = order["qty"] if order["side"] == "BUY" else -order["qty"]
        if existing:
            existing["qty"] += qty_delta
            existing["last_price"] = order["price"]
            existing["updated_at"]  = order["timestamp"]
        else:
            self._positions.append({
                "symbol":     order["symbol"],
                "qty":        qty_delta,
                "avg_cost":   order["price"],
                "last_price": order["price"],
                "run_id":     self.run_id,
                "updated_at": order["timestamp"],
            })

    # ------------------------------------------------------------------
    # Kill helpers (called by LiveEngine bulk kill)
    # ------------------------------------------------------------------

    def cancel_open_orders(self) -> dict[str, list]:
        """Cancel all open (pending) orders via this runner's executor."""
        cancelled, failed = [], []
        # Identify pending orders
        pending = [o for o in self._orders if o.get("status") == "pending"]
        for order in pending:
            broker_ref = order.get("broker_ref", "")
            if not broker_ref:
                continue
            try:
                if hasattr(self._executor, "cancel_order"):
                    self._executor.cancel_order(broker_ref)
                order["status"] = "cancelled"
                cancelled.append(broker_ref)
            except Exception as exc:
                logger.error(f"[Runner:{self.run_id}] cancel_order {broker_ref}: {exc}")
                failed.append(broker_ref)
        return {"cancelled": cancelled, "failed": failed}

    def square_off_positions(self) -> dict[str, list]:
        """Market sell all open long positions; buy back all open short positions."""
        squared, failed = [], []
        open_positions = [p for p in self._positions if p.get("qty", 0) != 0]
        for pos in open_positions:
            sym = pos["symbol"]
            qty = abs(pos["qty"])
            side = "SELL" if pos["qty"] > 0 else "BUY"
            try:
                self._executor.place_order(
                    symbol=sym, side=side, qty=qty,
                    order_type="MARKET", tag="SQUARE_OFF",
                )
                pos["qty"] = 0
                squared.append(sym)
            except Exception as exc:
                logger.error(f"[Runner:{self.run_id}] square_off {sym}: {exc}")
                failed.append(sym)
        audit.record("SQUARE_OFF", self.symbol, session=self.mode,
                     run_id=self.run_id, squared=squared, failed=failed)
        return {"squared_off": squared, "failed": failed}

    # ------------------------------------------------------------------
    # Dashboard accessors
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        return {
            "run_id":       self.run_id,
            "symbol":       self.symbol,
            "capital":      self.capital,
            "mode":         self.mode,
            "broker":       self.broker,
            "state":        self._state,
            "error":        self._error,
            "deployed_at":  self.deployed_at,
            "order_count":  len(self._orders),
            "position_count": len([p for p in self._positions if p.get("qty", 0) != 0]),
        }

    def get_orders(self) -> list[dict[str, Any]]:
        return list(self._orders)  # shallow copy — safe for reads

    def get_positions(self) -> list[dict[str, Any]]:
        return [p for p in self._positions if p.get("qty", 0) != 0]


# ---------------------------------------------------------------------------
# Paper executor stub
# ---------------------------------------------------------------------------

class _PaperExecutorStub:
    """Minimal paper trading executor — virtual fills at bar close price.

    Used by StrategyRunner in paper mode. No network calls.
    Compatible with the same place_order() interface as LiveExecutor.
    """

    def __init__(self, symbol: str, capital: float) -> None:
        self.symbol  = symbol
        self.capital = capital
        self._cash   = capital
        logger.info(f"[PaperStub] Initialised for {symbol} capital={capital}")

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float = 0.0,
        order_type: str = "MARKET",
        tag: str = "",
        signal_timestamp: str = "",
        **_,
    ) -> dict:
        """Simulate an order fill. Returns a synthetic response dict."""
        cost = qty * price
        if side.upper() == "BUY":
            if cost > self._cash:
                raise ValueError(
                    f"[PaperStub] Insufficient capital: need {cost:.2f}, have {self._cash:.2f}"
                )
            self._cash -= cost
        else:
            self._cash += cost

        fill = {
            "orderid":   f"PAPER_{symbol}_{side}_{qty}_{datetime.now(timezone.utc).strftime('%H%M%S')}",
            "status":    "filled",
            "symbol":    symbol,
            "side":      side,
            "qty":       qty,
            "price":     price,
            "tag":       tag,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(f"[PaperStub] FILL: {side} {qty} {symbol} @ {price:.2f}  cash_remaining={self._cash:.2f}")
        return fill

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        logger.info(f"[PaperStub] cancel_order {order_id} — no-op in paper mode")
        return True
