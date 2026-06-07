"""
Backtest EMA Cross strategy on Vedanta using Angel One candle data.

Credentials from env vars (set in CMD before running):
    ANGELONE_API_KEY, ANGELONE_CLIENT_ID,
    ANGELONE_PASSWORD, ANGELONE_TOTP_SECRET

Run:
    python scripts\\backtest_vedanta.py

No existing code is modified. Standalone script only.
"""

from __future__ import annotations

import os
import sys
import pandas as pd
from datetime import datetime, timedelta

SEP = "-" * 60

VEDANTA_TOKENS = [
    ("1660",  "VEDANTA NSE primary"),
    ("3063",  "VEDANTA NSE alt-1"),
    ("14977", "VEDANTA NSE alt-2"),
]


def _login():
    from brokers.adapters.angelone import AngelOneBroker
    broker = AngelOneBroker()
    ok = broker.login()
    if not ok:
        print("[FAIL] Angel One login failed.")
        sys.exit(1)
    print(f"[OK]  Logged in as {os.getenv('ANGELONE_CLIENT_ID')}")
    return broker


def _fetch_candles(broker, days: int = 365) -> pd.DataFrame:
    to_dt    = datetime.now()
    from_dt  = to_dt - timedelta(days=days)
    from_str = from_dt.strftime("%Y-%m-%d %H:%M")
    to_str   = to_dt.strftime("%Y-%m-%d %H:%M")

    print(SEP)
    print("STEP 1 — Fetching Vedanta (NSE) daily candles from Angel One")
    print(f"         From : {from_str}")
    print(f"         To   : {to_str}")
    print(SEP)

    raw = []
    used_token = None
    for token, label in VEDANTA_TOKENS:
        print(f"  Trying token {token} ({label}) ...", end=" ")
        try:
            raw = broker.get_candles(
                exchange="NSE",
                symbol_token=token,
                interval="ONE_DAY",
                from_date=from_str,
                to_date=to_str,
            )
        except Exception as e:
            print(f"error: {e}")
            raw = []
        if raw:
            print(f"OK ({len(raw)} bars)")
            used_token = token
            break
        else:
            print("empty")

    if not raw:
        print("[FAIL] All tokens returned empty. Check Angel One scrip master.")
        broker.logout()
        sys.exit(1)

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    print()
    print(f"[OK]  {len(df)} candles fetched  (token={used_token})")
    print(f"      First bar : {df['timestamp'].iloc[0].date()}")
    print(f"      Last bar  : {df['timestamp'].iloc[-1].date()}")
    print(f"      Last close: {df['close'].iloc[-1]:.2f}")
    return df


def _run_backtest(df: pd.DataFrame) -> None:
    print(SEP)
    print("STEP 2 — Running EMA Cross backtest")
    print(SEP)

    from backtesting.engine import BacktestEngine
    from strategies.ema_cross import EMACrossStrategy

    engine = BacktestEngine(
        strategy_cls=EMACrossStrategy,
        symbol="VEDANTA",
        data=df,
        capital=100_000.0,
        params={"fast": 9, "slow": 21},
    )
    result = engine.run()

    print()
    print("=" * 60)
    print(" BACKTEST RESULTS — VEDANTA | EMA 9/21 Cross | 1Y Daily")
    print("=" * 60)
    print(f"  Symbol          : {result.symbol}")
    print(f"  Strategy        : {result.strategy_name}")
    print(f"  Capital         : {result.initial_capital:,.0f}")
    print(f"  Final Value     : {result.final_value:,.2f}")
    print(f"  Net P&L         : {result.net_pnl:,.2f}")
    print(f"  Return          : {result.return_pct:.2f}%")
    print(f"  Max Drawdown    : {result.max_drawdown_pct:.2f}%")
    print(f"  Total Trades    : {result.total_trades}")
    print(f"  Win Rate        : {result.win_rate:.1f}%")
    print(f"  Profit Factor   : {result.profit_factor:.2f}")
    print(f"  Sharpe Ratio    : {result.sharpe_ratio:.2f}")
    print()

    if result.trades:
        print(f"  Last 5 trades:")
        print(f"  {'Entry':>12}  {'Exit':>12}  {'Side':>5}  {'P&L':>10}  {'Ret%':>7}")
        print(f"  {'':->12}  {'':->12}  {'':->5}  {'':->10}  {'':->7}")
        for t in result.trades[-5:]:
            pnl      = getattr(t, 'pnl', 0)
            ret      = getattr(t, 'return_pct', 0)
            side     = getattr(t, 'side', '?')
            entry_dt = getattr(t, 'entry_time', '?')
            exit_dt  = getattr(t, 'exit_time',  '?')
            print(f"  {str(entry_dt)[:10]:>12}  {str(exit_dt)[:10]:>12}  {str(side):>5}  {pnl:>10.2f}  {ret:>7.2f}%")
    print()


def main():
    required = ["ANGELONE_API_KEY", "ANGELONE_CLIENT_ID",
                "ANGELONE_PASSWORD", "ANGELONE_TOTP_SECRET"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print("[FAIL] Missing env vars:")
        for k in missing:
            print(f"       set {k}=your_value")
        sys.exit(1)

    broker = _login()
    df     = _fetch_candles(broker, days=365)
    broker.logout()
    _run_backtest(df)


if __name__ == "__main__":
    main()
