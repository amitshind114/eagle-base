"""Live trading session bootstrap — Phase 9.

Entry point for each trading day. Run once at market open:

    EAGLE_LIVE_ENABLED=true python scripts/live_session.py

Flow:
    1. Validate all env vars
    2. executor.connect()  — credentials + token map + reconcile
    3. executor.reconcile() — confirm 0 discrepancies before first order
    4. Start scheduler:
           09:00  pre_market_check()
           09:15  market_open()     ← strategy signals start here
           15:20  market_close()    ← square off open positions
           15:35  post_market_report()
    5. SIGTERM / SIGINT → graceful_shutdown() → square off all + audit summary

First instrument: NIFTYBEES (NIFTY ETF)
    - Highly liquid (millions of shares/day)
    - No F&O complexity
    - Tracks NIFTY index cleanly
    - max_position_value = ₹5,000
    - Strategy: SMA Crossover (20, 50) on 5m data
    - Paper portfolio runs in parallel — signals must match
"""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Project root on path ───────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.audit import audit
from core.logger import get_logger
from live.executor import LIVE_ENABLED, DuplicateOrderError, LiveExecutor

log = get_logger("live_session")
IST = ZoneInfo("Asia/Kolkata")

# ── Config ───────────────────────────────────────────────────────────────
FIRST_SYMBOLS   = ["NIFTYBEES"]                   # Week 1: ETF only
EXPANDED_SYMBOLS = ["NIFTYBEES", "RELIANCE", "HDFCBANK", "INFY", "TCS"]  # After 5 clean days
MAX_POSITION_VALUE = 5_000                         # ₹5,000 hard cap per position
STRATEGY_NAME   = "SMA Crossover"
STRATEGY_PARAMS = {"fast": 20, "slow": 50}
INTERVAL        = "5m"

# ── Required env vars (validated before anything runs) ─────────────────────
REQUIRED_VARS = [
    "ANGEL_API_KEY",
    "ANGEL_CLIENT_ID",
    "ANGEL_PASSWORD",
    "ANGEL_TOTP_SECRET",
    "EAGLE_LIVE_ENABLED",
]

# ── Globals ────────────────────────────────────────────────────────────────
executor: LiveExecutor | None = None
_shutdown_requested = False


# ── Step 1: Validate env vars ─────────────────────────────────────────────

def validate_env() -> None:
    """Fail loudly listing every missing var before any network call."""
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v, "").strip()]
    if missing:
        raise ValueError(
            f"\n[live_session] Missing required environment variables:\n"
            + "\n".join(f"  ✗  {v}" for v in missing)
            + "\n\nAdd them to your .env file and restart."
        )
    if not LIVE_ENABLED:
        raise RuntimeError(
            "EAGLE_LIVE_ENABLED is not 'true'. "
            "Set EAGLE_LIVE_ENABLED=true in .env ONLY after paper validation."
        )
    log.info("[live_session] ✓ All env vars present.")


# ── Scheduled jobs ───────────────────────────────────────────────────────────

def pre_market_check() -> None:
    """09:00 IST — Warm-up checks before market opens."""
    log.info("[09:00] Pre-market check starting...")
    audit.record("PRE_MARKET_START", "SYSTEM", session="live")

    # Refresh token map
    try:
        from instruments.token_map import refresh_if_stale, token_count
        refresh_if_stale()
        log.info(f"[09:00] Token map: {token_count()} instruments ready.")
    except Exception as exc:
        log.error(f"[09:00] Token map refresh failed: {exc}")
        audit.record("PRE_MARKET_ERROR", "SYSTEM", session="live", error=str(exc))

    # Final reconcile before trading begins
    if executor:
        result = executor.reconcile()
        if any(result.values()):
            log.warning(f"[09:00] Reconcile discrepancies found: {result}")
            audit.record("PRE_MARKET_RECONCILE_WARN", "SYSTEM", session="live",
                         discrepancies=result)
        else:
            log.info("[09:00] ✓ Reconcile: 0 discrepancies.")

    audit.record("PRE_MARKET_DONE", "SYSTEM", session="live")


def market_open() -> None:
    """09:15 IST — Market opens: begin signal generation loop."""
    log.info("[09:15] Market open. Starting signal loop...")
    audit.record("MARKET_OPEN", "SYSTEM", session="live")

    # Determine active symbols
    symbols = _get_active_symbols()
    log.info(f"[09:15] Active symbols: {symbols}")

    # Start strategy in background thread
    import threading
    t = threading.Thread(
        target=_signal_loop,
        args=(symbols,),
        daemon=True,
        name="signal_loop",
    )
    t.start()


def market_close() -> None:
    """15:20 IST — Square off all open positions before exchange close."""
    global _shutdown_requested
    log.info("[15:20] Market close: squaring off all positions...")
    audit.record("MARKET_CLOSE_SQUAREOFF", "SYSTEM", session="live")
    _square_off_all(reason="EOD")
    _shutdown_requested = True


def post_market_report() -> None:
    """15:35 IST — Write daily summary to audit log."""
    log.info("[15:35] Post-market report...")
    today_events   = audit.today(session="live")
    trades         = [e for e in today_events if e.get("event") == "ORDER_PLACED"]
    reconciles     = [e for e in today_events if "RECONCILE" in e.get("event", "")]
    discrepancies  = [e for e in reconciles if e.get("event") != "RECONCILE_NONE"]

    total_pnl = sum(float(e.get("pnl", 0)) for e in today_events if "pnl" in e)

    # Position values
    pos_values: list[float] = []
    if executor:
        for pos in executor.get_positions():
            qty   = abs(int(pos.get("netqty", 0)))
            price = float(pos.get("ltp", 0))
            pos_values.append(qty * price)
    max_position = max(pos_values) if pos_values else 0.0

    audit.daily_summary(
        session="live",
        total_trades=len(trades),
        total_pnl=round(total_pnl, 2),
        max_position_value=round(max_position, 2),
        reconcile_discrepancies=len(discrepancies),
    )
    log.info(
        f"[15:35] Day summary — trades={len(trades)} pnl={total_pnl:.2f} "
        f"max_pos={max_position:.2f} discrepancies={len(discrepancies)}"
    )


# ── Signal loop ─────────────────────────────────────────────────────────────────

def _signal_loop(symbols: list[str]) -> None:
    """Runs in background thread 09:15 – 15:20.

    Every bar (5m), fetch data, generate signals, compare with paper portfolio,
    place live orders only if paper and live agree.
    """
    from data.fetcher import DataFetcher
    from paper.portfolio import PaperPortfolio
    from strategies.sma_crossover import SMACrossover

    fetcher         = DataFetcher()
    live_strategy   = SMACrossover(**STRATEGY_PARAMS)
    paper_strategy  = SMACrossover(**STRATEGY_PARAMS)
    paper_portfolio = PaperPortfolio(capital=len(symbols) * MAX_POSITION_VALUE)

    log.info(f"[signal_loop] Started: symbols={symbols} interval={INTERVAL}")

    while not _shutdown_requested:
        now = datetime.now(tz=IST)
        # Only trade during market hours
        if not (now.hour == 9 and now.minute >= 15) and not (9 < now.hour < 15) and not (now.hour == 15 and now.minute < 20):
            time.sleep(30)
            continue

        for sym in symbols:
            try:
                df = fetcher.fetch(sym, period="5d", interval=INTERVAL)
                if df is None or df.empty:
                    log.warning(f"[signal_loop] No data for {sym}")
                    continue

                # Live signal
                live_sig = live_strategy.generate_signals(df).iloc[-1]
                # Paper signal (must match)
                paper_sig = paper_strategy.generate_signals(df).iloc[-1]

                if live_sig != paper_sig:
                    log.warning(
                        f"[signal_loop] SIGNAL MISMATCH {sym}: "
                        f"live={live_sig} paper={paper_sig}. Skipping live order."
                    )
                    audit.record("SIGNAL_MISMATCH", sym, session="live",
                                 live_signal=int(live_sig), paper_signal=int(paper_sig))
                    continue

                ltp   = float(df["Close"].iloc[-1])
                qty   = max(1, int(MAX_POSITION_VALUE // ltp))

                if live_sig == 1:
                    _place_safe(sym, "BUY", qty, ltp)
                    paper_portfolio.on_signal("BUY", sym, ltp, qty)
                elif live_sig == -1:
                    _place_safe(sym, "SELL", qty, ltp)
                    paper_portfolio.on_signal("SELL", sym, ltp, qty)

            except Exception as exc:
                log.error(f"[signal_loop] Error processing {sym}: {exc}")
                audit.record("SIGNAL_LOOP_ERROR", sym, session="live", error=str(exc))

        # Wait for next 5m bar
        time.sleep(300)


def _place_safe(
    symbol: str, side: str, qty: int, price: float,
) -> None:
    """Place order with idempotency and position value guard."""
    if executor is None:
        return
    # ₹5,000 position value guard
    if qty * price > MAX_POSITION_VALUE:
        qty = max(1, int(MAX_POSITION_VALUE // price))

    ts = datetime.now(tz=IST).isoformat()
    try:
        executor.place_order(
            symbol=symbol, side=side, qty=qty, price=price,
            signal_timestamp=ts,
        )
    except DuplicateOrderError:
        log.info(f"[place_safe] Duplicate blocked: {side} {symbol}")
    except Exception as exc:
        log.error(f"[place_safe] Order failed [{symbol}]: {exc}")


# ── Square off ───────────────────────────────────────────────────────────────────

def _square_off_all(reason: str = "SHUTDOWN") -> None:
    """Square off every open position at market price."""
    if executor is None:
        return
    positions = executor.get_positions()
    if not positions:
        log.info(f"[square_off] No open positions to square off ({reason}).")
        return
    for pos in positions:
        sym = str(pos.get("tradingsymbol", "")).upper()
        qty = abs(int(pos.get("netqty", 0)))
        if qty == 0:
            continue
        # If long → sell; if short → buy
        net = int(pos.get("netqty", 0))
        side = "SELL" if net > 0 else "BUY"
        try:
            executor.place_order(
                symbol=sym, side=side, qty=qty,
                signal_timestamp=f"SQUAREOFF_{reason}_{datetime.now(tz=IST).isoformat()}",
            )
            log.info(f"[square_off] {side} {qty} {sym} ({reason})")
            audit.record("SQUARE_OFF", sym, session="live",
                         side=side, qty=qty, reason=reason)
        except Exception as exc:
            log.error(f"[square_off] Failed {sym}: {exc}")
            audit.record("SQUARE_OFF_ERROR", sym, session="live",
                         error=str(exc), reason=reason)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_active_symbols() -> list[str]:
    """Return symbol list based on how many clean days have passed."""
    clean_days = int(os.environ.get("EAGLE_CLEAN_DAYS", "0"))
    if clean_days >= 5:
        return EXPANDED_SYMBOLS
    return FIRST_SYMBOLS


# ── Graceful shutdown ────────────────────────────────────────────────────────────

def graceful_shutdown(signum=None, frame=None) -> None:
    """SIGTERM / SIGINT handler.

    1. Square off all open positions
    2. Write post-market report
    3. Exit cleanly
    """
    global _shutdown_requested
    _shutdown_requested = True
    log.info(f"[shutdown] Signal {signum} received. Initiating graceful shutdown...")
    audit.record("SHUTDOWN_REQUESTED", "SYSTEM", session="live", signum=signum)

    _square_off_all(reason="SIGTERM")
    post_market_report()

    log.info("[shutdown] Done. Exiting.")
    sys.exit(0)


# ── Scheduler ───────────────────────────────────────────────────────────────────

def _run_scheduler() -> None:
    """Simple scheduler: checks HH:MM every 30s and fires jobs once per day."""
    JOBS = {
        "09:00": pre_market_check,
        "09:15": market_open,
        "15:20": market_close,
        "15:35": post_market_report,
    }
    fired: set[str] = set()

    log.info("[scheduler] Running. Waiting for market events...")
    while not _shutdown_requested:
        now_hm = datetime.now(tz=IST).strftime("%H:%M")
        for hm, job in JOBS.items():
            if now_hm == hm and hm not in fired:
                log.info(f"[scheduler] Firing job at {hm}: {job.__name__}")
                try:
                    job()
                except Exception as exc:
                    log.error(f"[scheduler] Job {job.__name__} failed: {exc}")
                    audit.record("SCHEDULER_JOB_ERROR", "SYSTEM", session="live",
                                 job=job.__name__, error=str(exc))
                fired.add(hm)
        # Reset fired jobs at midnight
        if now_hm == "00:00":
            fired.clear()
        time.sleep(30)


# ── Entry point ──────────────────────────────────────────────────────────────────

def main() -> None:
    global executor

    log.info("=" * 60)
    log.info(" EAGLE LIVE SESSION STARTING")
    log.info(f" Date: {datetime.now(tz=IST).strftime('%Y-%m-%d %H:%M IST')}")
    log.info("=" * 60)

    # 1. Validate env vars
    validate_env()

    # 2. Connect to broker (validates creds + token map + reconcile internally)
    executor = LiveExecutor()
    executor.connect()
    log.info("[main] ✓ Broker connection established.")

    # 3. Pre-flight reconcile
    result = executor.reconcile()
    if any(result.values()):
        log.warning(f"[main] Pre-flight reconcile found discrepancies: {result}")
        log.warning("[main] Review and resolve before relying on position data.")
    else:
        log.info("[main] ✓ Pre-flight reconcile: 0 discrepancies.")

    # 4. Register signal handlers
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT,  graceful_shutdown)
    log.info("[main] ✓ Signal handlers registered (SIGTERM, SIGINT).")

    # 5. Run scheduler (blocks until 15:35 or SIGTERM)
    audit.record("SESSION_READY", "SYSTEM", session="live",
                 symbols=_get_active_symbols(),
                 max_position_value=MAX_POSITION_VALUE)
    _run_scheduler()


if __name__ == "__main__":
    main()
