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

Paper mode wiring (as of this commit)::
  - Uses real PaperExecutor + PaperPortfolio (NOT _PaperExecutorStub)
  - portfolio.restore() called at init → positions survive restarts
  - portfolio.persist() called after every fill → atomic SQLite write
  - get_positions() / get_orders() read from portfolio books (source of truth)
  - _PaperExecutorStub is retained for test compatibility — NOT deleted

Live mode is UNCHANGED — still uses LiveExecutor + place_order() interface.

Thread safety:
  - _state transitions protected by _lock
  - _orders and _positions lists retained for live mode (GIL-safe appends)
  - PaperPortfolio writes serialised through the single tick thread

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
from pathlib import Path
from typing import Any, Type

from core.audit import audit
from core.logger import logger

# Tick interval in seconds (default: 60s = 1-minute bars)
_DEFAULT_TICK_INTERVAL: float = float(
    __import__("os").environ.get("EAGLE_TICK_INTERVAL", "60")
)

# SQLite storage root for per-runner paper portfolios
_DATA_DIR = Path(
    __import__("os").environ.get("EAGLE_DATA_DIR", "eagle_base/data")
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
        self.run_id         = run_id
        self.symbol         = symbol
        self.capital        = capital
        self.mode           = mode           # "paper" | "live"
        self.broker         = broker
        self.params         = params
        self.deployed_at    = datetime.now(timezone.utc).isoformat()
        self._tick_interval = tick_interval

        self._state: str = RunnerState.CREATED
        self._lock        = threading.Lock()
        self._stop_event  = threading.Event()
        self._pause_event = threading.Event()   # set = paused
        self._thread: threading.Thread | None = None
        self._error: str | None = None

        # Retained for live mode compatibility (GIL-safe append-only lists)
        self._orders:    list[dict[str, Any]] = []
        self._positions: list[dict[str, Any]] = []

        # Paper portfolio reference (None in live mode)
        self._portfolio = None

        # Instantiate strategy
        self._strategy = strategy_cls(symbol=symbol, capital=capital, params=params)

        # Instantiate executor (sets self._portfolio for paper mode)
        self._executor = self._build_executor()

        logger.info(
            f"[Runner:{run_id}] Initialised — "
            f"{strategy_cls.__name__}/{symbol}/{mode}"
        )

    # ------------------------------------------------------------------
    # Executor factory
    # ------------------------------------------------------------------

    def _build_executor(self):
        """Return executor instance. Sets self._portfolio for paper mode.

        Paper mode: PaperExecutor(PaperPortfolio) — real engine, SQLite-backed.
                    Falls back to _PaperExecutorStub on ImportError so existing
                    tests and CI continue to pass without paper/ dependencies.
        Live mode:  LiveExecutor (Angel One SmartAPI) — unchanged.
        """
        if self.mode == "live":
            from live.executor import LiveExecutor
            executor = LiveExecutor()
            executor.connect()
            return executor

        # ── Paper mode: try real engine first ───────────────────────────
        try:
            from paper.portfolio import PaperPortfolio
            from paper.executor import PaperExecutor

            db_path = _DATA_DIR / f"paper_{self.run_id}.db"
            portfolio = PaperPortfolio(cash=self.capital, db_path=db_path)

            restored = portfolio.restore()
            if restored:
                logger.info(
                    f"[Runner:{self.run_id}] Paper portfolio restored from {db_path}"
                )
            else:
                logger.info(
                    f"[Runner:{self.run_id}] New paper portfolio — "
                    f"cash={self.capital:,.0f}"
                )

            self._portfolio = portfolio
            return PaperExecutor(portfolio=portfolio)

        except ImportError as exc:
            # Graceful fallback — keeps tests green if paper/ deps missing
            logger.warning(
                f"[Runner:{self.run_id}] PaperExecutor import failed ({exc}); "
                f"falling back to _PaperExecutorStub"
            )
            return _PaperExecutorStub(symbol=self.symbol, capital=self.capital)

    # ------------------------------------------------------------------
    # Lifecycle  (UNCHANGED)
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
        """Signal the tick loop to stop."""
        with self._lock:
            if self._state in (RunnerState.STOPPED, RunnerState.STOPPING):
                return
            self._state = RunnerState.STOPPING

        self._stop_event.set()
        self._pause_event.clear()  # unblock if paused

        if not force and self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)

        # Final persist on graceful stop
        self._safe_persist()

        with self._lock:
            self._state = RunnerState.STOPPED

        audit.record("RUNNER_STOPPED", self.symbol, session=self.mode, run_id=self.run_id)
        logger.info(f"[Runner:{self.run_id}] Stopped (force={force}).")

    # ------------------------------------------------------------------
    # Tick loop  (UNCHANGED)
    # ------------------------------------------------------------------

    def _tick_loop(self) -> None:
        """Main strategy execution loop — runs in background thread."""
        with self._lock:
            self._state = RunnerState.RUNNING

        logger.info(
            f"[Runner:{self.run_id}] Tick loop started "
            f"(interval={self._tick_interval}s)."
        )

        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(1.0)
                continue

            try:
                self._tick()
            except Exception as exc:
                logger.error(f"[Runner:{self.run_id}] Tick error: {exc}")
                audit.record(
                    "RUNNER_TICK_ERROR", self.symbol, session=self.mode,
                    run_id=self.run_id, error=str(exc),
                )
                with self._lock:
                    self._error = str(exc)
                    self._state = RunnerState.ERROR
                break

            self._stop_event.wait(timeout=self._tick_interval)

        with self._lock:
            if self._state not in (RunnerState.ERROR,):
                self._state = RunnerState.STOPPED

        logger.info(f"[Runner:{self.run_id}] Tick loop exited.")

    def _tick(self) -> None:
        """Single tick: fetch bar → strategy.on_bar() → execute signal."""
        bar = self._fetch_latest_bar()
        if bar is None:
            logger.debug(f"[Runner:{self.run_id}] No bar data — skipping tick.")
            return

        signal = self._strategy.on_bar(bar)
        if signal is None:
            return

        self._execute_signal(signal, bar)

    def _fetch_latest_bar(self) -> dict | None:
        """Fetch latest OHLCV bar (yfinance fallback)."""
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

    # ------------------------------------------------------------------
    # Signal execution  ─ CHANGED: paper path uses PaperExecutor.execute()
    # ------------------------------------------------------------------

    def _execute_signal(self, signal: dict, bar: dict) -> None:
        """Route signal to executor.

        Paper mode  → PaperExecutor.execute() → ExecutionResult → persist()
        Live mode   → LiveExecutor.place_order()  (unchanged)
        Stub mode   → _PaperExecutorStub.place_order() (unchanged)
        """
        side  = signal.get("side")        # "BUY" | "SELL"
        qty   = int(signal.get("qty", 1))
        price = float(bar.get("close", 0.0))

        if not side or qty <= 0 or price <= 0:
            return

        # ── Paper path (real PaperExecutor) ────────────────────────────
        if self._portfolio is not None:
            try:
                from paper.executor import PaperExecutor
                if isinstance(self._executor, PaperExecutor):
                    result = self._executor.execute(
                        signal=side,
                        symbol=self.symbol,
                        price=price,
                        qty=qty,
                        avg_volume=int(bar.get("volume", 0)),
                    )
                    if not result.success:
                        logger.warning(
                            f"[Runner:{self.run_id}] Paper order REJECTED: "
                            f"{result.reason}"
                        )
                        audit.record(
                            "PAPER_ORDER_REJECTED", self.symbol, session="paper",
                            run_id=self.run_id, reason=result.reason,
                            side=side, qty=qty, price=price,
                        )
                        return

                    # Atomic persist after every fill
                    self._safe_persist()

                    audit.record(
                        "PAPER_ORDER_FILLED", self.symbol, session="paper",
                        run_id=self.run_id, order_id=result.order_id,
                        side=side, qty=qty,
                        req_price=result.req_price,
                        exec_price=result.exec_price,
                        slippage=result.slippage,
                        impact=result.impact,
                    )
                    logger.info(
                        f"[Runner:{self.run_id}] PAPER FILL — "
                        f"{side} {qty} {self.symbol} @ {result.exec_price:.2f}  "
                        f"slip={result.slippage:.4f} impact={result.impact:.4f}"
                    )
                    return   # ← done; skip legacy path below

            except ImportError:
                pass  # fall through to legacy place_order() path

        # ── Live path + stub fallback (place_order interface) ────────────
        try:
            result = self._executor.place_order(
                symbol=self.symbol,
                side=side,
                qty=qty,
                price=price,
                signal_timestamp=bar.get("timestamp", ""),
            )
            order_record = {
                "run_id":     self.run_id,
                "symbol":     self.symbol,
                "side":       side,
                "qty":        qty,
                "price":      price,
                "status":     "filled",
                "timestamp":  datetime.now(timezone.utc).isoformat(),
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
        """Update internal position list (live/stub mode only)."""
        if order.get("status") != "filled":
            return
        existing = next(
            (p for p in self._positions if p["symbol"] == order["symbol"]), None
        )
        qty_delta = order["qty"] if order["side"] == "BUY" else -order["qty"]
        if existing:
            existing["qty"]        += qty_delta
            existing["last_price"]  = order["price"]
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
    # Persistence helper  (NEW)
    # ------------------------------------------------------------------

    def _safe_persist(self) -> None:
        """Persist portfolio — swallows exceptions so tick loop never crashes."""
        if self._portfolio is None:
            return
        try:
            self._portfolio.persist()
        except Exception as exc:
            logger.error(f"[Runner:{self.run_id}] persist() failed: {exc}")

    # ------------------------------------------------------------------
    # Kill helpers  (UNCHANGED logic, paper square-off enhanced)
    # ------------------------------------------------------------------

    def cancel_open_orders(self) -> dict[str, list]:
        """Cancel all open (pending) orders."""
        cancelled, failed = [], []
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
        """Market-close all open positions."""
        squared, failed = [], []

        # Paper: use portfolio.position_book as source of truth
        if self._portfolio is not None:
            for pos in self._portfolio.position_book.all_open():
                if pos.quantity == 0:
                    continue
                side = "SELL" if pos.quantity > 0 else "BUY"
                qty  = abs(pos.quantity)
                try:
                    from paper.executor import PaperExecutor
                    if isinstance(self._executor, PaperExecutor):
                        bar = self._fetch_latest_bar()
                        price = bar["close"] if bar else pos.avg_cost
                        result = self._executor.execute(
                            signal=side, symbol=pos.symbol,
                            price=price, qty=qty,
                        )
                        if result.success:
                            squared.append(pos.symbol)
                        else:
                            failed.append(pos.symbol)
                except Exception as exc:
                    logger.error(
                        f"[Runner:{self.run_id}] paper square_off "
                        f"{pos.symbol}: {exc}"
                    )
                    failed.append(pos.symbol)
            self._safe_persist()

        else:
            # Live / stub: use _positions list (unchanged)
            open_positions = [p for p in self._positions if p.get("qty", 0) != 0]
            for pos in open_positions:
                sym  = pos["symbol"]
                qty  = abs(pos["qty"])
                side = "SELL" if pos["qty"] > 0 else "BUY"
                try:
                    self._executor.place_order(
                        symbol=sym, side=side, qty=qty,
                        order_type="MARKET", tag="SQUARE_OFF",
                    )
                    pos["qty"] = 0
                    squared.append(sym)
                except Exception as exc:
                    logger.error(
                        f"[Runner:{self.run_id}] live square_off {sym}: {exc}"
                    )
                    failed.append(sym)

        audit.record(
            "SQUARE_OFF", self.symbol, session=self.mode,
            run_id=self.run_id, squared=squared, failed=failed,
        )
        return {"squared_off": squared, "failed": failed}

    # ------------------------------------------------------------------
    # Dashboard accessors  ─ CHANGED: paper reads from portfolio books
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        snap = self._portfolio.snapshot() if self._portfolio else None
        return {
            "run_id":           self.run_id,
            "symbol":           self.symbol,
            "capital":          self.capital,
            "mode":             self.mode,
            "broker":           self.broker,
            "state":            self._state,
            "error":            self._error,
            "deployed_at":      self.deployed_at,
            # Legacy counts (live/stub mode)
            "order_count":      len(self._orders),
            "position_count":   len([p for p in self._positions if p.get("qty", 0) != 0]),
            # Portfolio fields (paper mode; None in live mode)
            "cash":             snap.cash            if snap else None,
            "total_value":      snap.total_value      if snap else None,
            "unrealized_pnl":   snap.unrealized_pnl   if snap else None,
            "realized_pnl":     snap.realized_pnl     if snap else None,
            "daily_pnl":        snap.daily_pnl        if snap else None,
            "open_positions":   snap.open_positions   if snap else None,
            "total_trades":     snap.total_trades     if snap else None,
            "corrupted":        snap.corrupted        if snap else False,
        }

    def get_orders(self) -> list[dict[str, Any]]:
        """Paper: trade_book (filled trades). Live/stub: _orders list."""
        if self._portfolio is not None:
            return [
                {
                    "run_id":       self.run_id,
                    "trade_id":     t.trade_id,
                    "symbol":       t.symbol,
                    "side":         t.side.value,
                    "qty":          t.quantity,
                    "price":        t.price,
                    "realized_pnl": t.realized_pnl,
                    "timestamp":    t.timestamp.isoformat(),
                    "mode":         "paper",
                }
                for t in self._portfolio.trade_book.all()
            ]
        return list(self._orders)

    def get_positions(self) -> list[dict[str, Any]]:
        """Paper: position_book. Live/stub: _positions list."""
        if self._portfolio is not None:
            return [
                {
                    "run_id":     self.run_id,
                    "symbol":     pos.symbol,
                    "qty":        pos.quantity,
                    "avg_cost":   pos.avg_cost,
                    "last_price": pos.current_price,
                    "mode":       "paper",
                }
                for pos in self._portfolio.position_book.all_open()
                if pos.quantity != 0
            ]
        return [p for p in self._positions if p.get("qty", 0) != 0]


# ---------------------------------------------------------------------------
# Paper executor stub  ─ RETAINED (used by tests, not deleted)
# ---------------------------------------------------------------------------

class _PaperExecutorStub:
    """Minimal paper trading executor — virtual fills at bar close price.

    Retained for test compatibility. StrategyRunner uses the real
    PaperExecutor in production; this stub is the ImportError fallback.
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
        logger.info(
            f"[PaperStub] FILL: {side} {qty} {symbol} @ {price:.2f}  "
            f"cash_remaining={self._cash:.2f}"
        )
        return fill

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        logger.info(f"[PaperStub] cancel_order {order_id} — no-op in paper mode")
        return True
