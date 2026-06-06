"""MultiStockRunner — Phase 04 hardened.

Runs a strategy against a list of symbols independently,
collects BacktestResult per symbol, and returns a ranked
MultiStockResult leaderboard.

Phase 04 changes:
  - _FETCH_SEMAPHORE = threading.Semaphore(5) caps concurrent yfinance calls.
    Without this, 50 threads hitting yfinance simultaneously on NIFTY50
    runs reliably triggers HTTP 429 Rate Limited responses.
  - Exponential backoff on HTTP 429: sleep(2**attempt + random.random()) x4.
  - _run_single wraps fetch inside the semaphore context.

Key design decisions:
  - Each symbol runs in isolation — no shared state / capital.
  - A failed symbol (bad data, missing history) never aborts the run.
  - Optionally parallel via concurrent.futures for speed.
  - Registry is updated after the run so UI shows latest results.

Usage:
    from backtesting.multi_runner import MultiStockRunner
    from backtesting.universe import load_universe
    from strategies.ema_crossover import EmaCrossover

    runner = MultiStockRunner()
    result = runner.run(
        strategy=EmaCrossover(fast=12, slow=26),
        symbols=load_universe("NIFTY50"),
        period="1y",
        capital=100_000,
    )
    print(result.summary())
    print(result.leaderboard().head(10))
"""

from __future__ import annotations

import random
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from core.logger import get_logger
from backtesting.result import BacktestResult
from backtesting.multi_result import MultiStockResult
from strategies.base import BaseStrategy

log = get_logger("backtesting.multi_runner")

# Default interval used when none specified
_DEFAULT_INTERVAL = "1d"
# Max worker threads for parallel runs
_MAX_WORKERS = 4

# Phase 04: Semaphore caps concurrent yfinance fetches to 5 at a time.
# Without this, a NIFTY50 run with max_workers=10 fires 50 simultaneous
# HTTP requests to Yahoo Finance, which reliably returns HTTP 429.
_FETCH_SEMAPHORE = threading.Semaphore(5)

# Backoff config for HTTP 429 rate-limit handling
_MAX_RETRIES   = 4
_BASE_BACKOFF  = 2.0   # seconds (doubled each attempt: 2, 4, 8, 16)


class MultiStockRunner:
    """Run a strategy on multiple symbols and return a leaderboard.

    Args:
        max_workers : Number of parallel threads (default 4).
                      Set to 1 to disable parallelism for debugging.
        update_registry: If True, push results back to StrategyRegistry.
    """

    def __init__(
        self,
        max_workers: int = _MAX_WORKERS,
        update_registry: bool = True,
    ) -> None:
        self.max_workers      = max_workers
        self.update_registry  = update_registry

    # ───────────────────────────────────────────────────────────────
    # Public API
    # ───────────────────────────────────────────────────────────────

    def run(
        self,
        strategy: BaseStrategy,
        symbols: list[str],
        period: str = "1y",
        capital: float = 100_000.0,
        interval: str = _DEFAULT_INTERVAL,
    ) -> MultiStockResult:
        """Run the strategy on every symbol independently.

        Args:
            strategy : A concrete BaseStrategy instance.
            symbols  : List of Yahoo Finance symbols e.g. load_universe('NIFTY50').
            period   : yfinance period string. e.g. '1y', '3y', '5y'.
            capital  : Starting capital per symbol (not shared).
            interval : OHLCV interval e.g. '1d', '1wk'.

        Returns:
            MultiStockResult with leaderboard + failed list.
        """
        log.info(
            f"[multi_runner] Starting run: strategy={strategy.name} "
            f"symbols={len(symbols)} period={period} capital={capital:,.0f}"
        )

        results: dict[str, BacktestResult] = {}
        failed:  list[str]                 = []

        if self.max_workers > 1:
            results, failed = self._run_parallel(strategy, symbols, period, capital, interval)
        else:
            results, failed = self._run_serial(strategy, symbols, period, capital, interval)

        msr = MultiStockResult(
            results=results,
            failed_symbols=failed,
            strategy_name=strategy.name,
            period=period,
            capital=capital,
        )

        log.info(
            f"[multi_runner] Completed: ok={msr.successful_symbols} "
            f"failed={len(failed)} avg_sharpe={msr.avg_sharpe()}"
        )

        if self.update_registry:
            self._update_registry(strategy.name, msr)

        return msr

    # ───────────────────────────────────────────────────────────────
    # Execution strategies
    # ───────────────────────────────────────────────────────────────

    def _run_serial(
        self,
        strategy: BaseStrategy,
        symbols: list[str],
        period: str,
        capital: float,
        interval: str,
    ) -> tuple[dict[str, BacktestResult], list[str]]:
        results: dict[str, BacktestResult] = {}
        failed:  list[str] = []
        for symbol in symbols:
            result = self._run_single(strategy, symbol, period, capital, interval)
            if result is not None:
                results[symbol] = result
            else:
                failed.append(symbol)
        return results, failed

    def _run_parallel(
        self,
        strategy: BaseStrategy,
        symbols: list[str],
        period: str,
        capital: float,
        interval: str,
    ) -> tuple[dict[str, BacktestResult], list[str]]:
        results: dict[str, BacktestResult] = {}
        failed:  list[str] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_map = {
                pool.submit(
                    self._run_single, strategy, symbol, period, capital, interval
                ): symbol
                for symbol in symbols
            }
            for future in as_completed(future_map):
                symbol = future_map[future]
                try:
                    result = future.result()
                    if result is not None:
                        results[symbol] = result
                    else:
                        failed.append(symbol)
                except Exception as exc:
                    log.warning(f"[multi_runner] Unhandled future error {symbol}: {exc}")
                    failed.append(symbol)

        return results, failed

    def _run_single(
        self,
        strategy: BaseStrategy,
        symbol: str,
        period: str,
        capital: float,
        interval: str,
    ) -> Optional[BacktestResult]:
        """Run one symbol inside the fetch semaphore with exponential backoff.

        Phase 04: acquire _FETCH_SEMAPHORE before calling the runner so at
        most 5 yfinance requests are in-flight at any moment. On HTTP 429,
        retry up to _MAX_RETRIES times with jittered exponential backoff.
        """
        last_exc: Exception = RuntimeError("no attempt made")

        for attempt in range(_MAX_RETRIES):
            try:
                with _FETCH_SEMAPHORE:
                    from backtesting.runner import BacktestRunner
                    runner = BacktestRunner(
                        symbol=symbol,
                        strategy=strategy,
                        capital=capital,
                        period=period,
                        interval=interval,
                    )
                    result = runner.run()
                log.debug(
                    f"[multi_runner] {symbol}: return={result.total_return_pct:.2f}% "
                    f"trades={result.total_trades}"
                )
                return result

            except Exception as exc:
                last_exc = exc
                exc_str  = str(exc).lower()
                # Retry on rate-limit (HTTP 429) or transient network errors
                is_rate_limit = "429" in exc_str or "too many" in exc_str or "rate" in exc_str
                is_transient  = "timeout" in exc_str or "connection" in exc_str

                if (is_rate_limit or is_transient) and attempt < _MAX_RETRIES - 1:
                    sleep_secs = (_BASE_BACKOFF ** attempt) + random.random()
                    log.warning(
                        f"[multi_runner] {symbol} attempt {attempt+1}/{_MAX_RETRIES}: "
                        f"{exc}. Retrying in {sleep_secs:.1f}s"
                    )
                    time.sleep(sleep_secs)
                    continue

                # Non-retryable error or max retries reached
                log.warning(
                    f"[multi_runner] {symbol} FAILED after {attempt+1} attempt(s): {last_exc}\n"
                    + traceback.format_exc(limit=3)
                )
                return None

        log.warning(f"[multi_runner] {symbol} exhausted all {_MAX_RETRIES} retries.")
        return None

    # ───────────────────────────────────────────────────────────────
    # Registry update
    # ───────────────────────────────────────────────────────────────

    def _update_registry(
        self, strategy_name: str, msr: MultiStockResult
    ) -> None:
        """Push a summary result into StrategyRegistry after the multi-run."""
        try:
            from strategies.registry import StrategyRegistry
            reg = StrategyRegistry()
            reg.update_result(strategy_name, msr)
        except Exception as exc:
            log.debug(f"[multi_runner] registry update skipped: {exc}")
