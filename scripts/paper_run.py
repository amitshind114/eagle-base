"""scripts/paper_run.py — 5-day paper trading validation runner.

Loads 3 strategies (SMA, EMA, RSI) and replays 5m intraday data for
10 liquid NSE stocks.  Designed to run Monday–Friday; kill and restart
it each day — portfolio state must be identical before and after each
restart thanks to atomic SQLite persistence.

Usage:
    python scripts/paper_run.py
    python scripts/paper_run.py --symbols RELIANCE TCS INFY --days 5
    python scripts/paper_run.py --fresh          # wipe state and start over

Outputs:
    - Logs every signal / order / position change to stdout + logs/paper_run.log
    - Writes daily_report_YYYYMMDD.txt at 15:30 IST each session
    - Persists state to eagle_base/data/paper_portfolio.db on every bar
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/paper_run.log", mode="a"),
    ],
)
log = logging.getLogger("paper_run")

# ---------------------------------------------------------------------------
# Default universe — 10 liquid NSE F&O stocks
# ---------------------------------------------------------------------------
DEFAULT_SYMBOLS = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "WIPRO.NS",    "AXISBANK.NS", "SBIN.NS", "BAJFINANCE.NS", "MARUTI.NS",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Eagle paper trading runner")
    p.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    p.add_argument("--days",    type=int, default=5,  help="Replay days of 5m data")
    p.add_argument("--cash",    type=float, default=500_000.0)
    p.add_argument("--fresh",   action="store_true", help="Wipe saved state and start over")
    p.add_argument("--interval", default="5m")
    return p.parse_args()


def build_portfolio(cash: float, fresh: bool, fetcher):
    """Create or restore PaperPortfolio."""
    from paper.portfolio import PaperPortfolio
    db = Path("eagle_base/data/paper_portfolio.db")
    if fresh and db.exists():
        db.unlink()
        log.info("[paper_run] Wiped existing portfolio state (--fresh)")
    portfolio = PaperPortfolio(cash=cash, fetcher=fetcher)
    restored = portfolio.restore()
    if portfolio.is_corrupted:
        log.critical("[paper_run] CORRUPTED state detected on restore — aborting.")
        sys.exit(1)
    if restored:
        log.info("[paper_run] Restored portfolio: %s", portfolio)
    else:
        log.info("[paper_run] Fresh portfolio: cash=%.0f", cash)
    return portfolio


def load_strategies():
    """Import and instantiate all 3 strategies."""
    from strategies.sma_crossover   import SmaCrossover
    from strategies.ema_crossover   import EmaCrossover
    from strategies.rsi_mean_reversion import RsiMeanReversion
    return {
        "SMA": SmaCrossover(),
        "EMA": EmaCrossover(),
        "RSI": RsiMeanReversion(),
    }


def fetch_data(fetcher, symbol: str, interval: str, days: int):
    """Fetch OHLCV bars for replay."""
    period = f"{days}d"
    try:
        df = fetcher.fetch(symbol, period=period, interval=interval)
        return df
    except Exception as exc:
        log.warning("[paper_run] fetch failed for %s: %s", symbol, exc)
        return None


def run_symbol_session(
    symbol: str,
    df,
    strategies: dict,
    executor,
    bar_idx: int,
) -> dict:
    """Run one bar through all 3 strategies, execute signals."""
    results = {}
    for name, strategy in strategies.items():
        try:
            signals = strategy.generate_signals(df.iloc[: bar_idx + 1])
            signal_val = signals.iloc[-1]
            if signal_val == 1:
                result = executor.execute("BUY", symbol, qty=1)
                if result.success:
                    log.info("[%s] BUY  %s bar=%d price=%.2f", name, symbol, bar_idx, result.exec_price)
            elif signal_val == -1:
                result = executor.execute("SELL", symbol, qty=1)
                if result.success:
                    log.info("[%s] SELL %s bar=%d price=%.2f", name, symbol, bar_idx, result.exec_price)
            results[name] = signal_val
        except Exception as exc:
            log.warning("[paper_run] strategy %s failed on %s bar %d: %s", name, symbol, bar_idx, exc)
    return results


def daily_report(portfolio, session_date: date) -> str:
    """Generate and save end-of-day report."""
    snap = portfolio.snapshot()
    pnl  = portfolio.daily_pnl()
    report = (
        f"=== Daily Report {session_date} ===\n"
        f"  Cash          : {snap.cash:>12,.2f}\n"
        f"  Open positions: {snap.open_positions:>4}\n"
        f"  Realized PnL  : {snap.realized_pnl:>+12,.2f}\n"
        f"  Unrealized PnL: {snap.unrealized_pnl:>+12,.2f}\n"
        f"  Daily PnL     : {pnl:>+12,.2f}\n"
        f"  Total value   : {snap.total_value:>12,.2f}\n"
        f"  Total trades  : {snap.total_trades:>4}\n"
        f"  Corrupted     : {snap.corrupted}\n"
        "=" * 35
    )
    out_path = Path(f"logs/daily_report_{session_date.strftime('%Y%m%d')}.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    log.info("[paper_run] Daily report saved: %s", out_path)
    print(report)
    return report


def main() -> None:
    args = parse_args()
    Path("logs").mkdir(exist_ok=True)

    log.info("=" * 60)
    log.info("Eagle Paper Trading Runner")
    log.info("Symbols   : %s", args.symbols)
    log.info("Days      : %d", args.days)
    log.info("Interval  : %s", args.interval)
    log.info("Cash      : %.0f", args.cash)
    log.info("=" * 60)

    # DataFetcher
    try:
        from data.fetcher import DataFetcher
        fetcher = DataFetcher()
    except ImportError:
        log.warning("[paper_run] data.fetcher not available — using stub fetcher")
        fetcher = None

    portfolio  = build_portfolio(args.cash, args.fresh, fetcher)
    strategies = load_strategies()

    from paper.executor import PaperExecutor
    executor = PaperExecutor(portfolio=portfolio, fetcher=fetcher)

    # --- Data fetch phase ---
    log.info("[paper_run] Fetching data for %d symbols...", len(args.symbols))
    data: dict[str, object] = {}
    for sym in args.symbols:
        df = fetch_data(fetcher, sym, args.interval, args.days) if fetcher else None
        if df is not None and not df.empty:
            data[sym] = df
            log.info("[paper_run] Loaded %d bars for %s", len(df), sym)
        else:
            log.warning("[paper_run] No data for %s — skipping", sym)

    if not data:
        log.error("[paper_run] No data loaded — cannot run. Check fetcher / network.")
        sys.exit(1)

    # --- Replay loop ---
    max_bars = max(len(df) for df in data.values())
    log.info("[paper_run] Starting replay: %d bars", max_bars)

    for bar_idx in range(30, max_bars):   # skip first 30 bars for indicator warmup
        for sym, df in data.items():
            if bar_idx >= len(df):
                continue
            run_symbol_session(sym, df, strategies, executor, bar_idx)

        # Persist on every bar — cheap with WAL
        portfolio.persist()

        # Progress log every 100 bars
        if bar_idx % 100 == 0:
            snap = portfolio.snapshot()
            log.info(
                "[paper_run] bar=%d cash=%.0f positions=%d trades=%d pnl=%+.0f",
                bar_idx, snap.cash, snap.open_positions,
                snap.total_trades, snap.total_value - args.cash,
            )

    # --- End-of-session report ---
    daily_report(portfolio, date.today())
    portfolio.persist()
    log.info("[paper_run] Session complete. Portfolio persisted.")


if __name__ == "__main__":
    main()
