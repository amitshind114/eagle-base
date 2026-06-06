"""Core backtesting engine — runs a strategy on historical OHLCV data.

Phase-02 accuracy fixes applied:
  - Look-ahead bias   : signals.shift(1) after generate_signals()
  - Sharpe annualise  : interval-aware PERIODS dict (not hardcoded 252)
  - Buy-hold curve    : capital * close/close[0]  (not pct_change cumprod)
  - avg_win/loss pct  : % of trade cost, not % of total capital
  - STT rate          : product_type param — MIS=0.025%, CNC=0.1% both sides
  - Forced-close fix  : equity[-1] set correctly after last-bar close
  - Min-bars guard    : 10 bars (strategy warmup is strategy's responsibility)

Signal-safety fix (Python 3.13 + pandas 2.x):
  - signals NaN cleaned BEFORE shift so astype(int) never sees NaN
  - MultiIndex columns from yfinance 2.x flattened before dropna

Accurate NSE cost model:
    - Slippage  : configurable fill-price offset (default 0.05%)
    - Brokerage : flat Rs20 per executed order (Zerodha MIS default)
    - STT       : 0.025% sell-side (MIS) or 0.1% both sides (CNC delivery)
    - Exchange  : 0.00335% NSE transaction charge
    - SEBI      : 0.0001% on turnover
    - Stamp     : 0.003% on buy-side turnover
    - GST       : 18% on (brokerage + exchange charge)

Usage:
    from backtesting.engine import BacktestEngine
    engine = BacktestEngine(symbol="RELIANCE.NS", initial_capital=200_000)
    result = engine.run(df, strategy)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from backtesting.models import BacktestResult, Trade
from core.exceptions import BacktestError, InsufficientDataError
from core.logger import get_logger

if TYPE_CHECKING:
    from strategies.base import BaseStrategy

log = get_logger("backtesting.engine")

# ── Interval → annualisation periods ────────────────────────────────────
PERIODS: dict[str, int] = {
    "1m":  252 * 375,
    "3m":  252 * 125,
    "5m":  252 * 75,
    "15m": 252 * 25,
    "30m": 252 * 12,
    "1h":  252 * 6,
    "1d":  252,
    "1wk": 52,
    "1mo": 12,
}

# ── NSE charge constants ─────────────────────────────────────────────────
_BROKERAGE_FLAT  = 20.0
_STT_MIS_SELL    = 0.00025
_STT_CNC_SIDE    = 0.001
_EXCHANGE_CHARGE = 0.0000335
_SEBI_CHARGE     = 0.000001
_STAMP_BUY       = 0.00003
_GST             = 0.18


def _nse_charges(turnover: float, side: str, product_type: str = "MIS") -> float:
    """Total NSE charges in INR for one leg of a trade."""
    brokerage = _BROKERAGE_FLAT
    if product_type == "CNC":
        stt = turnover * _STT_CNC_SIDE
    else:
        stt = turnover * _STT_MIS_SELL if side == "SELL" else 0.0
    exchange = turnover * _EXCHANGE_CHARGE
    sebi     = turnover * _SEBI_CHARGE
    stamp    = turnover * _STAMP_BUY if side == "BUY" else 0.0
    gst      = (brokerage + exchange) * _GST
    return brokerage + stt + exchange + sebi + stamp + gst


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize DataFrame columns to Title Case (Open/High/Low/Close/Volume).

    Also handles:
    - yfinance 2.x MultiIndex columns  e.g. ('Close', 'RELIANCE.NS')
    - lowercase / UPPERCASE column names
    """
    # ── Flatten MultiIndex columns (yfinance 2.x multi-ticker format) ───
    if isinstance(df.columns, pd.MultiIndex):
        # Take the first level — ('Close','RELIANCE.NS') → 'Close'
        df = df.copy()
        df.columns = [str(c[0]) if isinstance(c, tuple) else str(c)
                      for c in df.columns]

    rename = {}
    for orig in df.columns:
        low = str(orig).strip().lower()
        if low == "open":
            rename[orig] = "Open"
        elif low == "high":
            rename[orig] = "High"
        elif low == "low":
            rename[orig] = "Low"
        elif low == "close":
            rename[orig] = "Close"
        elif low in ("volume", "vol"):
            rename[orig] = "Volume"
        elif low in ("adj close", "adj_close"):
            rename[orig] = "Adj Close"
    return df.rename(columns=rename)


def _safe_signals(raw: pd.Series) -> np.ndarray:
    """Convert a raw strategy signal Series to a clean int numpy array.

    Handles the Python 3.13 + pandas 2.x issue where:
      - rolling() produces float NaN in the warmup window
      - astype(int) on a float-NaN Series raises OverflowError on Windows

    Safe pipeline:
      1. fillna(0)   — kill NaN FIRST, before any cast
      2. shift(1)    — look-ahead bias fix (act on bar N+1)
      3. fillna(0)   — shift introduces one new NaN at position 0
      4. round()     — defensive: e.g. 0.9999 → 1 not 0
      5. clip(-1, 1) — clamp to valid signal range
      6. astype(int) — safe cast, no NaN present
    """
    return (
        raw
        .fillna(0)          # step 1 — NaN gone before any numeric op
        .shift(1)           # step 2 — look-ahead fix
        .fillna(0)          # step 3 — shift NaN at index 0
        .round()            # step 4 — float drift guard
        .clip(-1, 1)        # step 5 — clamp to {-1, 0, 1}
        .astype(int)        # step 6 — safe, no NaN present
        .to_numpy()
    )


class BacktestEngine:
    """Event-driven backtesting engine with accurate NSE cost simulation."""

    MIN_BARS = 10

    def __init__(
        self,
        symbol: str = "",
        initial_capital: float = 100_000.0,
        commission_pct: float = 0.0,
        slippage_pct: float = 0.0005,
        interval: str = "1d",
        product_type: str = "MIS",
    ) -> None:
        self.symbol          = symbol
        self.initial_capital = initial_capital
        self.slippage_pct    = slippage_pct
        self.interval        = interval
        self.product_type    = product_type.upper()

    def run(self, df: pd.DataFrame, strategy: "BaseStrategy") -> BacktestResult:
        """Run strategy on OHLCV df and return a fully populated BacktestResult."""
        if df is None or df.empty:
            raise InsufficientDataError("DataFrame is None or empty")

        df = df.copy()
        df = _normalize_columns(df)

        if "Close" not in df.columns:
            raise BacktestError(
                f"No 'Close' column after normalization. "
                f"Columns found: {list(df.columns)}"
            )

        # Drop rows where Close is NaN
        df = df.dropna(subset=["Close"])
        n_valid = len(df)
        if n_valid < self.MIN_BARS:
            raise InsufficientDataError(
                f"Too few valid Close bars after NaN drop "
                f"(have {n_valid}, need {self.MIN_BARS})"
            )

        # ── Generate signals then apply look-ahead fix safely ────────────
        raw_signals: pd.Series = strategy.generate_signals(df)

        if not isinstance(raw_signals, pd.Series):
            raw_signals = pd.Series(raw_signals, index=df.index)

        if len(raw_signals) != len(df):
            raise BacktestError(
                f"signals length {len(raw_signals)} != df length {len(df)}"
            )

        # Re-index to df to ensure alignment after any strategy internal ops
        raw_signals = raw_signals.reindex(df.index)

        # Safe conversion: fillna BEFORE shift BEFORE astype(int)
        sig_arr = _safe_signals(raw_signals)

        strategy_name = getattr(strategy, "name", type(strategy).__name__)

        capital   = self.initial_capital
        cash      = capital
        position  = 0
        avg_cost  = 0.0
        entry_date       = None
        entry_price_fill = 0.0
        equity: list[float] = []
        trades: list[Trade] = []
        total_charges = 0.0
        intraday = self.interval != "1d"

        close_arr = df["Close"].to_numpy(dtype=float)
        open_arr  = df["Open"].to_numpy(dtype=float) if "Open" in df.columns else close_arr
        idx_arr   = df.index

        for i in range(len(df)):
            sig   = int(sig_arr[i])
            close = float(close_arr[i])
            ts    = idx_arr[i]

            # Intraday: fill at next-bar open; daily: fill at close
            if intraday and i + 1 < len(df):
                fill_open = float(open_arr[i + 1])
            else:
                fill_open = close

            # ── BUY entry ───────────────────────────────────────────────
            if sig == 1 and position == 0 and close > 0:
                fill_price = fill_open * (1 + self.slippage_pct)
                qty        = int(cash * 0.95 / fill_price)
                if qty > 0:
                    turnover          = fill_price * qty
                    charges           = _nse_charges(turnover, "BUY", self.product_type)
                    cash             -= (turnover + charges)
                    avg_cost          = fill_price
                    entry_price_fill  = fill_price
                    entry_date        = ts
                    position          = qty
                    total_charges    += charges

            # ── SELL exit ───────────────────────────────────────────────
            elif sig == -1 and position > 0 and close > 0:
                fill_price  = fill_open * (1 - self.slippage_pct)
                turnover    = fill_price * position
                charges     = _nse_charges(turnover, "SELL", self.product_type)
                trade_cost  = avg_cost * position
                gross_pnl   = (fill_price - avg_cost) * position
                net_pnl     = gross_pnl - charges
                pnl_pct     = net_pnl / trade_cost * 100 if trade_cost > 0 else 0.0
                cash       += turnover - charges
                total_charges += charges

                trades.append(Trade(
                    symbol      = self.symbol,
                    direction   = "LONG",
                    entry_date  = entry_date,
                    exit_date   = ts,
                    entry_price = round(entry_price_fill, 4),
                    exit_price  = round(fill_price, 4),
                    quantity    = position,
                    pnl         = round(net_pnl, 4),
                    pnl_pct     = round(pnl_pct, 4),
                    exit_reason = "SIGNAL",
                ))
                position = 0
                avg_cost = 0.0

            equity.append(cash + position * close)

        # ── Forced close at end of data ──────────────────────────────────
        if position > 0:
            last_close  = float(df["Close"].iloc[-1])
            fill_price  = last_close * (1 - self.slippage_pct)
            turnover    = fill_price * position
            charges     = _nse_charges(turnover, "SELL", self.product_type)
            trade_cost  = avg_cost * position
            net_pnl     = (fill_price - avg_cost) * position - charges
            pnl_pct     = net_pnl / trade_cost * 100 if trade_cost > 0 else 0.0
            cash       += turnover - charges
            total_charges += charges
            equity[-1]  = cash  # position closed — no MTM

            trades.append(Trade(
                symbol      = self.symbol,
                direction   = "LONG",
                entry_date  = entry_date,
                exit_date   = df.index[-1],
                entry_price = round(entry_price_fill, 4),
                exit_price  = round(fill_price, 4),
                quantity    = position,
                pnl         = round(net_pnl, 4),
                pnl_pct     = round(pnl_pct, 4),
                exit_reason = "END_OF_DATA",
            ))

        # ── Equity series ────────────────────────────────────────────────
        if equity:
            equity_series = pd.Series(equity, index=df.index, dtype=float)
        else:
            equity_series = pd.Series(
                [float(capital)] * len(df), index=df.index, dtype=float
            )
        equity_series = equity_series.ffill().fillna(float(capital))

        bh_series = capital * (df["Close"] / float(df["Close"].iloc[0]))
        dd_series = (equity_series / equity_series.cummax()) - 1

        final_cap    = float(equity_series.iloc[-1])
        total_return = (final_cap - capital) / capital * 100
        bh_return    = (float(bh_series.iloc[-1]) - capital) / capital * 100
        max_dd       = float(dd_series.min() * 100)

        if not trades:
            max_dd = 0.0
            final_cap    = float(capital)
            total_return = 0.0

        ann_periods = PERIODS.get(self.interval, 252)
        strat_rets  = equity_series.pct_change().fillna(0)
        std         = float(strat_rets.std())
        sharpe      = float(strat_rets.mean() / std * np.sqrt(ann_periods)) if std > 0 else 0.0

        trades_pnl  = [t.pnl for t in trades]
        wins        = [p for p in trades_pnl if p > 0]
        losses      = [p for p in trades_pnl if p <= 0]
        n_trades    = len(trades_pnl)
        win_rate    = len(wins) / n_trades * 100 if n_trades else 0.0

        win_trades  = [t for t in trades if t.pnl > 0]
        loss_trades = [t for t in trades if t.pnl <= 0]
        avg_win  = (
            sum(t.pnl / (t.entry_price * t.quantity) * 100 for t in win_trades)
            / len(win_trades) if win_trades else 0.0
        )
        avg_loss = (
            sum(t.pnl / (t.entry_price * t.quantity) * 100 for t in loss_trades)
            / len(loss_trades) if loss_trades else 0.0
        )

        pf_num = sum(wins)
        pf_den = abs(sum(losses))
        if pf_den > 0:
            profit_factor = round(pf_num / pf_den, 4)
        elif pf_num > 0:
            profit_factor = 999.0
        else:
            profit_factor = 0.0

        log.info(
            f"{self.symbol} | Return={total_return:.1f}% Sharpe={sharpe:.2f} "
            f"MaxDD={max_dd:.1f}% WR={win_rate:.1f}% Trades={n_trades} "
            f"Charges=Rs{total_charges:,.0f}"
        )

        return BacktestResult(
            symbol              = self.symbol,
            strategy_name       = strategy_name,
            trades              = trades,
            equity_curve        = equity_series,
            buy_hold_curve      = bh_series,
            drawdown_series     = dd_series,
            total_return_pct    = round(total_return, 2),
            buy_hold_return_pct = round(bh_return, 2),
            sharpe_ratio        = round(sharpe, 3),
            max_drawdown_pct    = round(max_dd, 2),
            win_rate_pct        = round(win_rate, 2),
            total_trades        = n_trades,
            profit_factor       = profit_factor,
            avg_win_pct         = round(avg_win, 3),
            avg_loss_pct        = round(avg_loss, 3),
            final_capital       = round(final_cap, 2),
        )
