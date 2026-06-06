"""LiveEngine — singleton orchestrator for all live StrategyRunners.

This is THE central hub that api/routers/live.py talks to.
All 10 live endpoints resolve through LiveEngine.instance().

Responsibilities:
  - Maintain registry of active StrategyRunners keyed by run_id
  - Provide deploy / pause / resume / stop per-runner controls
  - Provide bulk kill operations (kill_all_strategies, cancel_all_orders, square_off_all)
  - Expose aggregated status / positions / orders for the dashboard
  - Track engine uptime and global state

Safety invariants:
  - Engine is a singleton; call LiveEngine.instance() everywhere
  - EAGLE_LIVE_ENABLED=false (default) means deploy() raises immediately
  - kill_* methods work even when EAGLE_LIVE_ENABLED=false (safe to call on shutdown)

Usage::

    engine = LiveEngine.instance()
    run_id = engine.deploy(strategy_id="ema_cross", symbol="RELIANCE",
                           capital=50000.0, mode="live", broker="angelone")
    engine.stop(run_id)
    engine.kill_all_strategies()
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from core.audit import audit
from core.logger import logger

LIVE_ENABLED: bool = os.environ.get("EAGLE_LIVE_ENABLED", "false").lower() == "true"


class LiveEngine:
    """Singleton live trading engine."""

    _instance: Optional["LiveEngine"] = None
    _lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Singleton accessor
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "LiveEngine":
        """Return (or create) the global LiveEngine singleton."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        if LiveEngine._instance is not None:
            raise RuntimeError("Use LiveEngine.instance() — do not instantiate directly.")
        self._runners: dict[str, Any] = {}          # run_id -> StrategyRunner
        self._started_at: datetime = datetime.now(timezone.utc)
        self._state: str = "idle"                   # idle | running | stopping | stopped
        self._runners_lock: threading.Lock = threading.Lock()
        logger.info("[LiveEngine] Singleton initialised.")
        audit.record("ENGINE_INIT", "SYSTEM", session="live")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def uptime_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self._started_at).total_seconds()

    @property
    def runner_count(self) -> int:
        with self._runners_lock:
            return len(self._runners)

    # ------------------------------------------------------------------
    # Deploy
    # ------------------------------------------------------------------

    def deploy(
        self,
        strategy_id: str,
        symbol: str,
        capital: float,
        mode: str = "paper",
        broker: str = "angelone",
        params: dict | None = None,
    ) -> str:
        """Instantiate and start a StrategyRunner. Returns run_id.

        Args:
            strategy_id: registry key, e.g. "ema_cross"
            symbol:      trading symbol, e.g. "RELIANCE"
            capital:     allocated capital in INR
            mode:        "paper" (default) or "live"
            broker:      broker adapter key, e.g. "angelone"
            params:      optional strategy parameter overrides

        Raises:
            RuntimeError: if mode=="live" and EAGLE_LIVE_ENABLED=false
            KeyError:     if strategy_id not found in registry
        """
        if mode == "live" and not LIVE_ENABLED:
            raise RuntimeError(
                "Cannot deploy in LIVE mode: EAGLE_LIVE_ENABLED=false. "
                "Set EAGLE_LIVE_ENABLED=true in .env after paper validation."
            )

        from strategies.registry import get_strategy_class
        from live.runner import StrategyRunner

        strategy_cls = get_strategy_class(strategy_id)
        run_id = f"{strategy_id}_{symbol}_{uuid.uuid4().hex[:8]}"

        runner = StrategyRunner(
            run_id=run_id,
            strategy_cls=strategy_cls,
            symbol=symbol,
            capital=capital,
            mode=mode,
            broker=broker,
            params=params or {},
        )

        with self._runners_lock:
            self._runners[run_id] = runner
            self._state = "running"

        runner.start()
        audit.record(
            "RUNNER_DEPLOY", symbol, session=mode,
            run_id=run_id, strategy=strategy_id,
            capital=capital, broker=broker,
        )
        logger.info(f"[LiveEngine] Deployed runner {run_id} ({strategy_id}/{symbol}/{mode})")
        return run_id

    # ------------------------------------------------------------------
    # Per-runner controls
    # ------------------------------------------------------------------

    def pause(self, run_id: str) -> None:
        """Pause tick processing for a runner (no new signals)."""
        runner = self._get_runner(run_id)
        runner.pause()
        audit.record("RUNNER_PAUSE", runner.symbol, session=runner.mode, run_id=run_id)
        logger.info(f"[LiveEngine] Paused {run_id}")

    def resume(self, run_id: str) -> None:
        """Resume a paused runner."""
        runner = self._get_runner(run_id)
        runner.resume()
        audit.record("RUNNER_RESUME", runner.symbol, session=runner.mode, run_id=run_id)
        logger.info(f"[LiveEngine] Resumed {run_id}")

    def stop(self, run_id: str) -> None:
        """Gracefully stop a runner (completes current bar, then exits)."""
        runner = self._get_runner(run_id)
        runner.stop()
        with self._runners_lock:
            self._runners.pop(run_id, None)
            if not self._runners:
                self._state = "idle"
        audit.record("RUNNER_STOP", runner.symbol, session=runner.mode, run_id=run_id)
        logger.info(f"[LiveEngine] Stopped {run_id}")

    # ------------------------------------------------------------------
    # Bulk kill operations
    # ------------------------------------------------------------------

    def kill_all_strategies(self) -> dict[str, list[str]]:
        """Stop all runners immediately. Returns {stopped: [...], failed: [...]}."""
        stopped, failed = [], []
        with self._runners_lock:
            run_ids = list(self._runners.keys())

        for run_id in run_ids:
            try:
                runner = self._runners.get(run_id)
                if runner:
                    runner.stop(force=True)
                stopped.append(run_id)
            except Exception as exc:
                logger.error(f"[LiveEngine] kill_all_strategies: failed to stop {run_id}: {exc}")
                failed.append(run_id)

        with self._runners_lock:
            for run_id in stopped:
                self._runners.pop(run_id, None)
            self._state = "stopped" if not failed else "running"

        audit.record("KILL_ALL_STRATEGIES", "SYSTEM", session="live",
                     stopped=stopped, failed=failed)
        logger.warning(f"[LiveEngine] kill_all_strategies: stopped={stopped} failed={failed}")
        return {"stopped": stopped, "failed": failed}

    def cancel_all_orders(self, broker_adapter=None) -> dict[str, Any]:
        """Cancel all open orders across all runners via broker adapter.

        Args:
            broker_adapter: optional pre-authenticated broker instance.
                            If None, attempts to cancel via each runner's executor.

        Returns:
            {cancelled: [...order_ids], failed: [...order_ids]}
        """
        cancelled, failed = [], []

        with self._runners_lock:
            runners = list(self._runners.values())

        for runner in runners:
            try:
                result = runner.cancel_open_orders()
                cancelled.extend(result.get("cancelled", []))
                failed.extend(result.get("failed", []))
            except Exception as exc:
                logger.error(f"[LiveEngine] cancel_all_orders runner {runner.run_id}: {exc}")
                failed.append(runner.run_id)

        audit.record("KILL_ALL_ORDERS", "SYSTEM", session="live",
                     cancelled=cancelled, failed=failed)
        logger.warning(f"[LiveEngine] cancel_all_orders: cancelled={len(cancelled)} failed={len(failed)}")
        return {"cancelled": cancelled, "failed": failed}

    def square_off_all(self) -> dict[str, Any]:
        """Market square-off all open positions across all runners.

        Uses best-effort LTP from yfinance when live price feed is unavailable.
        Returns {squared_off: [...symbols], failed: [...symbols]}
        """
        squared, failed = [], []

        with self._runners_lock:
            runners = list(self._runners.values())

        for runner in runners:
            try:
                result = runner.square_off_positions()
                squared.extend(result.get("squared_off", []))
                failed.extend(result.get("failed", []))
            except Exception as exc:
                logger.error(f"[LiveEngine] square_off_all runner {runner.run_id}: {exc}")
                failed.append(runner.run_id)

        audit.record("KILL_ALL_POSITIONS", "SYSTEM", session="live",
                     squared_off=squared, failed=failed)
        logger.warning(f"[LiveEngine] square_off_all: squared={squared} failed={failed}")
        return {"squared_off": squared, "failed": failed}

    # ------------------------------------------------------------------
    # Status / dashboard aggregation
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Aggregate engine + all runner statuses for /api/live/status."""
        with self._runners_lock:
            runners_status = [
                runner.get_status() for runner in self._runners.values()
            ]
        return {
            "engine_state":    self._state,
            "uptime_seconds":  round(self.uptime_seconds, 1),
            "runner_count":    len(runners_status),
            "live_enabled":    LIVE_ENABLED,
            "runners":         runners_status,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        }

    def get_positions(self) -> list[dict[str, Any]]:
        """Aggregate open positions across all runners."""
        positions = []
        with self._runners_lock:
            for runner in self._runners.values():
                positions.extend(runner.get_positions())
        return positions

    def get_orders(self) -> list[dict[str, Any]]:
        """Aggregate order history across all runners."""
        orders = []
        with self._runners_lock:
            for runner in self._runners.values():
                orders.extend(runner.get_orders())
        return sorted(orders, key=lambda o: o.get("timestamp", ""), reverse=True)

    def list_runners(self) -> list[dict[str, Any]]:
        """Return summary list of all active runners."""
        with self._runners_lock:
            return [runner.get_status() for runner in self._runners.values()]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_runner(self, run_id: str):
        with self._runners_lock:
            runner = self._runners.get(run_id)
        if runner is None:
            raise KeyError(f"Runner '{run_id}' not found in LiveEngine.")
        return runner

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Gracefully shut down the engine. Called on app exit."""
        logger.info("[LiveEngine] Shutting down — stopping all runners.")
        self.kill_all_strategies()
        self._state = "stopped"
        audit.record("ENGINE_SHUTDOWN", "SYSTEM", session="live")
