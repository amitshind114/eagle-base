"""Live trading session entry point.

Flow (each trading day):
  1. Validate env vars (EAGLE_LIVE_ENABLED, broker credentials)
  2. executor.connect()  — establish broker WebSocket
  3. executor.reconcile() — sync internal book with broker
  4. scheduler.start()   — pre-market 09:00, open 09:15, close 15:20, report 15:35
  5. Register SIGTERM / SIGINT → graceful_shutdown() → square off all positions

Usage:
    python scripts/live_session.py
    python scripts/live_session.py --symbol NIFTYBEES --strategy sma_crossover

First-live defaults (P1 task):
    symbol   = NIFTYBEES
    strategy = sma_crossover (20, 50)
    max_position_value = ₹5,000
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# ── Logging setup (before any eagle imports) ──────────────────────────────────
from core.logger import get_logger
log = get_logger("scripts.live_session")

# ── Constants ─────────────────────────────────────────────────────────────────
DEFAULT_SYMBOL    = "NIFTYBEES"
DEFAULT_STRATEGY  = "sma_crossover"
DEFAULT_MAX_POS   = 5_000          # ₹ — Phase 09 Week-1 cap

# Market schedule (IST)
PRE_MARKET_HH_MM  = (9, 0)
MARKET_OPEN_HH_MM = (9, 15)
MARKET_CLOSE_HH_MM= (15, 20)
POST_MARKET_HH_MM = (15, 35)

_executor = None   # global so signal handler can reach it


# ── Step 1: Environment validation ────────────────────────────────────────────

REQUIRED_ENV_VARS = [
    "ANGEL_API_KEY",
    "ANGEL_CLIENT_ID",
    "ANGEL_PASSWORD",
    "ANGEL_TOTP_SECRET",
    "EAGLE_LIVE_ENABLED",
]

def validate_env() -> None:
    """Abort if any required env var is missing or EAGLE_LIVE_ENABLED != true."""
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        log.error(f"[live_session] Missing env vars: {missing}")
        sys.exit(1)

    if os.getenv("EAGLE_LIVE_ENABLED", "false").lower() != "true":
        log.error(
            "[live_session] EAGLE_LIVE_ENABLED is not 'true'. "
            "Set it explicitly to enable live trading."
        )
        sys.exit(1)

    log.info("[live_session] ✅ Env validation passed.")


# ── Step 2–3: Connect + reconcile ─────────────────────────────────────────────

def connect_and_reconcile(executor) -> None:
    log.info("[live_session] Connecting to broker…")
    executor.connect()
    log.info("[live_session] ✅ Broker connected.")

    log.info("[live_session] Running reconcile…")
    discrepancies = executor.reconcile()
    if discrepancies:
        log.warning(f"[live_session] ⚠️ {len(discrepancies)} reconcile discrepancies: {discrepancies}")
    else:
        log.info("[live_session] ✅ Reconcile clean — 0 discrepancies.")

    from core.audit import audit
    audit.record("SESSION_START", "SYSTEM", session="live",
                 reconcile_discrepancies=len(discrepancies) if discrepancies else 0)


# ── Step 4: Scheduler ─────────────────────────────────────────────────────────

def _wait_until(hh: int, mm: int, label: str) -> None:
    """Block until IST wall-clock reaches hh:mm. Logs every 5 min."""
    while True:
        now = datetime.now(tz=IST)
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        delta  = (target - now).total_seconds()
        if delta <= 0:
            return
        if delta > 300:
            log.info(f"[live_session] ⏳ Waiting for {label} ({int(delta//60)}m remaining)…")
        time.sleep(min(delta, 60))


def pre_market_check(executor, symbol: str) -> None:
    """09:00 — validate positions, print margin, warm data cache."""
    log.info("[live_session] 🌅 Pre-market check started (09:00 IST).")
    positions = executor.get_positions()
    log.info(f"[live_session]   Overnight positions: {len(positions)}")
    for p in positions:
        log.info(f"[live_session]     {p}")
    from core.audit import audit
    audit.record("PRE_MARKET", symbol, session="live",
                 overnight_positions=len(positions))


def market_open(executor, symbol: str, strategy_name: str,
                max_position_value: float) -> None:
    """09:15 — start strategy execution loop."""
    log.info("[live_session] 🔔 Market open (09:15 IST) — starting strategy.")
    try:
        from engine.runner import StrategyRunner
        runner = StrategyRunner(
            symbol=symbol,
            strategy_name=strategy_name,
            executor=executor,
            max_position_value=max_position_value,
            session="live",
        )
        runner.start()   # non-blocking; runs in background thread
        log.info(f"[live_session] ✅ Strategy '{strategy_name}' running on {symbol}.")
    except ImportError:
        log.warning("[live_session] StrategyRunner not yet wired — strategy loop skipped.")
    except Exception as exc:
        log.error(f"[live_session] Strategy start failed: {exc}")


def market_close(executor, symbol: str) -> None:
    """15:20 — square off all intraday positions before exchange closes."""
    log.info("[live_session] 🔔 Market close (15:20 IST) — squaring off positions.")
    try:
        executor.square_off_all(reason="EOD_CLOSE")
        log.info("[live_session] ✅ All positions squared off.")
    except Exception as exc:
        log.error(f"[live_session] Square-off failed: {exc}")


def post_market_report(executor, audit_log=None) -> None:
    """15:35 — reconcile, write daily summary, disconnect."""
    log.info("[live_session] 📋 Post-market report (15:35 IST).")
    try:
        discrepancies = executor.reconcile()
    except Exception:
        discrepancies = []

    from core.audit import audit as _audit
    al = audit_log or _audit
    events = al.today(session="live")
    trades = [e for e in events if e.get("event") == "ORDER_PLACED"]
    pnl    = sum(float(e.get("pnl", 0)) for e in events if "pnl" in e)
    max_pos = max(
        (abs(int(e.get("qty", 0))) * float(e.get("price", 0)) for e in trades),
        default=0.0,
    )

    al.daily_summary(
        session="live",
        total_trades=len(trades),
        total_pnl=pnl,
        max_position_value=max_pos,
        reconcile_discrepancies=len(discrepancies) if discrepancies else 0,
    )
    log.info(
        f"[live_session] Daily summary — trades={len(trades)} "
        f"pnl=₹{pnl:.2f} reconcile_issues={len(discrepancies) if discrepancies else 0}"
    )


def run_scheduler(executor, symbol: str, strategy_name: str,
                  max_position_value: float) -> None:
    """Block through the full trading day schedule."""
    _wait_until(*PRE_MARKET_HH_MM, "Pre-market (09:00)")
    pre_market_check(executor, symbol)

    _wait_until(*MARKET_OPEN_HH_MM, "Market open (09:15)")
    market_open(executor, symbol, strategy_name, max_position_value)

    _wait_until(*MARKET_CLOSE_HH_MM, "Market close (15:20)")
    market_close(executor, symbol)

    _wait_until(*POST_MARKET_HH_MM, "Post-market report (15:35)")
    post_market_report(executor)


# ── Step 5: Signal handlers ────────────────────────────────────────────────────

def graceful_shutdown(signum, frame) -> None:  # noqa: ANN001
    """SIGTERM / SIGINT → square off all positions and exit cleanly."""
    global _executor
    sig_name = signal.Signals(signum).name
    log.warning(f"[live_session] 🛑 Received {sig_name} — initiating graceful shutdown.")

    from core.audit import audit
    audit.record("SHUTDOWN_SIGNAL", "SYSTEM", session="live", signal=sig_name)

    if _executor is not None:
        try:
            log.warning("[live_session] Squaring off all positions before exit…")
            _executor.square_off_all(reason=f"SHUTDOWN_{sig_name}")
            log.info("[live_session] ✅ All positions squared off.")
        except Exception as exc:
            log.error(f"[live_session] Square-off on shutdown failed: {exc}")
        try:
            _executor.disconnect()
        except Exception:
            pass

    log.info("[live_session] Goodbye. 🦅")
    sys.exit(0)


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Eagle live trading session")
    p.add_argument("--symbol",   default=DEFAULT_SYMBOL,
                   help=f"Symbol to trade (default: {DEFAULT_SYMBOL})")
    p.add_argument("--strategy", default=DEFAULT_STRATEGY,
                   help=f"Strategy name (default: {DEFAULT_STRATEGY})")
    p.add_argument("--max-pos",  type=float, default=DEFAULT_MAX_POS,
                   help=f"Max position value ₹ (default: {DEFAULT_MAX_POS})")
    return p.parse_args()


def main() -> None:
    global _executor

    args = parse_args()
    log.info(
        f"[live_session] 🚀 Starting Eagle Live Session — "
        f"symbol={args.symbol} strategy={args.strategy} max_pos=₹{args.max_pos:,.0f}"
    )

    # 1. Validate env
    validate_env()

    # 2. Build executor
    try:
        from live.executor import LiveExecutor
        _executor = LiveExecutor()
    except Exception as exc:
        log.error(f"[live_session] Could not create LiveExecutor: {exc}")
        sys.exit(1)

    # 3. Signal handlers
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT,  graceful_shutdown)

    # 4. Connect + reconcile
    connect_and_reconcile(_executor)

    # 5. Run day scheduler (blocks until 15:35)
    run_scheduler(
        executor=_executor,
        symbol=args.symbol,
        strategy_name=args.strategy,
        max_position_value=args.max_pos,
    )

    # 6. Disconnect cleanly
    try:
        _executor.disconnect()
    except Exception:
        pass
    log.info("[live_session] ✅ Session complete. 🦅")


if __name__ == "__main__":
    main()
