"""Core backtesting engine — orchestrator.

Refactored (Phase 10):
  engine.py is a thin orchestrator of three independent components:

    CostModel         — NSE charge calculation
    TradeSimulator    — event loop: fills, equity curve, trade list
    MetricsCalculator — Sharpe, drawdown, win-rate (backtesting/metrics.py)

Fixes in this revision
----------------------
- H1 (tz alignment): df.index is stripped of timezone before any signal join.
  yfinance returns tz-aware UTC; pandas-ta returns naive. Mismatched indexes
  produce all-NaN signal columns — zero trades, no error. Fixed by calling
  _strip_tz(df) before generate_signals().
- H5 (freq='B' deprecation): all pd.date_range calls use pd.offsets.BDay()
  instead of freq='B', which becomes ValueError in pandas 3.x.
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

__all__ = ["BacktestEngine", "CostModel", "TradeSimulator"]

# ── Interval → annualisation periods ─────────────────────────────────────────
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


# ── Timezone normaliser ───────────────────────────────────────────────────────

def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Strip timezone from DataFrame index so yfinance (UTC-aware) and
    pandas-ta (tz-naive) indexes align correctly.

    Without this, df.join(signals) or pd.concat silently produces all-NaN
    signal columns — every backtest runs with zero trades.
    """
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


# ════════════════════════════════════════════════════════════════════════════
# CostModel
# ════════════════════════════════════════════════════════════════════════════

class CostModel:
    """NSE transaction cost calculator.

    Charges: Brokerage (₹20 flat), STT, Exchange, SEBI, Stamp, GST.
    """

    BROKERAGE_FLAT  = 20.0
    STT_MIS_SELL    = 0.00025
    STT_CNC_SIDE    = 0.001
    EXCHANGE_CHARGE = 0.0000335
    SEBI_CHARGE     = 0.000001
    STAMP_BUY       = 0.00003
    GST             = 0.18

    def __init__(self, product_type: str = "MIS") -> None:
        self.product_type = product_type.upper()

    def charges(self, turnover: float, side: str) -> float:
        brokerage = self.BROKERAGE_FLAT
        if self.product_type == "CNC":
            stt = turnover * self.STT_CNC_SIDE
        else:
            stt = turnover * self.STT_MIS_SELL if side == "SELL" else 0.0
        exchange = turnover * self.EXCHANGE_CHARGE
        sebi     = turnover * self.SEBI_CHARGE
        stamp    = turnover * self.STAMP_BUY if side == "BUY" else 0.0
        gst      = (brokerage + exchange) * self.GST
        return brokerage + stt + exchange + sebi + stamp + gst

    def round_trip(self, buy_turnover: float, sell_turnover: float) -> float:
        return self.charges(buy_turnover, "BUY") + self.charges(sell_turnover, "SELL")


# ════════════════════════════════════════════════════════════════════════════
# TradeSimulator
# ════════════════════════════════════════════════════════════════════════════

class TradeSimulator:
    """Simulates trade execution on a signal array + OHLCV DataFrame."""

    def __init__(
        self,
        symbol: str,
        initial_capital: float,
        cost_model: CostModel,
        slippage_pct: float = 0.0005,
        interval: str = "1d",
    ) -> None:
        self.symbol          = symbol
        self.initial_capital = initial_capital
        self.cost_model      = cost_model
        self.slippage_pct    = slippage_pct
        self.intraday        = interval != "1d"

    def run(
        self,
        df: pd.DataFrame,
        sig_arr: np.ndarray,
    ) -> tuple[list[Trade], list[float]]:
        cash             = float(self.initial_capital)
        position         = 0
        avg_cost         = 0.0
        entry_date       = None
        entry_price_fill = 0.0
        trades: list[Trade]  = []
        equity: list[float]  = []

        close_arr = df["Close"].to_numpy(dtype=float)
        open_arr  = df["Open"].to_numpy(dtype=float) if "Open" in df.columns else close_arr
        idx_arr   = df.index

        for i in range(len(df)):
            sig   = int(sig_arr[i])
            close = float(close_arr[i])
            ts    = idx_arr[i]

            fill_open = (
                float(open_arr[i + 1]) if (self.intraday and i + 1 < len(df)) else close
            )

            if sig == 1 and position == 0 and close > 0:
                fill_price = fill_open * (1 + self.slippage_pct)
                qty        = int(cash * 0.95 / fill_price)
                if qty > 0:
                    turnover         = fill_price * qty
                    charges          = self.cost_model.charges(turnover, "BUY")
                    cash            -= turnover + charges
                    avg_cost         = fill_price
                    entry_price_fill = fill_price
                    entry_date       = ts
                    position         = qty

            elif sig == -1 and position > 0 and close > 0:
                fill_price = fill_open * (1 - self.slippage_pct)
                turnover   = fill_price * position
                charges    = self.cost_model.charges(turnover, "SELL")
                trade_cost = avg_cost * position
                net_pnl    = (fill_price - avg_cost) * position - charges
                pnl_pct    = net_pnl / trade_cost * 100 if trade_cost > 0 else 0.0
                cash      += turnover - charges

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

        # Forced close at end-of-data
        if position > 0:
            last_close = float(df["Close"].iloc[-1])
            fill_price = last_close * (1 - self.slippage_pct)
            turnover   = fill_price * position
            charges    = self.cost_model.charges(turnover, "SELL")
            trade_cost = avg_cost * position
            net_pnl    = (fill_price - avg_cost) * position - charges
            pnl_pct    = net_pnl / trade_cost * 100 if trade_cost > 0 else 0.0
            cash      += turnover - charges
            if equity:
                equity[-1] = cash

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

        return trades, equity


# ── Signal helpers ────────────────────────────────────────────────────────────

def _safe_signals(raw: pd.Series) -> np.ndarray:
    return (
        raw
        .fillna(0)
        .shift(1)
        .fillna(0)
        .round()
        .clip(-1, 1)
        .astype(int)
        .to_numpy()
    )


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [str(c[0]) if isinstance(c, tuple) else str(c) for c in df.columns]
    rename = {}
    for orig in df.columns:
        low = str(orig).strip().lower()
        if low == "open":                rename[orig] = "Open"
        elif low == "high":              rename[orig] = "High"
        elif low == "low":               rename[orig] = "Low"
        elif low == "close":             rename[orig] = "Close"
        elif low in ("volume", "vol"):   rename[orig] = "Volume"
        elif low in ("adj close", "adj_close"): rename[orig] = "Adj Close"
    return df.rename(columns=rename)


# ════════════════════════════════════════════════════════════════════════════
# BacktestEngine — orchestrator
# ════════════════════════════════════════════════════════════════════════════

class BacktestEngine:
    """Orchestrates CostModel + TradeSimulator + MetricsCalculator."""

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
        self._cost_model     = CostModel(product_type)
        self._simulator      = TradeSimulator(
            symbol          = symbol,
            initial_capital = initial_capital,
            cost_model      = self._cost_model,
            slippage_pct    = slippage_pct,
            interval        = interval,
        )

    def run(self, df: pd.DataFrame, strategy: "BaseStrategy") -> BacktestResult:
        """Run strategy on OHLCV df and return BacktestResult."""
        if df is None or df.empty:
            raise InsufficientDataError("DataFrame is None or empty")

        df = df.copy()

        # FIX H1 — strip timezone so yfinance (UTC) and pandas-ta (naive) align
        df = _strip_tz(df)
        df = _normalize_columns(df)

        if "Close" not in df.columns:
            raise BacktestError(
                f"No 'Close' column after normalization. "
                f"Columns found: {list(df.columns)}"
            )

        df = df.dropna(subset=["Close"])
        if len(df) < self.MIN_BARS:
            raise InsufficientDataError(
                f"Too few valid bars (have {len(df)}, need {self.MIN_BARS})"
            )

        raw_signals: pd.Series = strategy.generate_signals(df)
        if not isinstance(raw_signals, pd.Series):
            raw_signals = pd.Series(raw_signals, index=df.index)
        if len(raw_signals) != len(df):
            raise BacktestError(
                f"signals length {len(raw_signals)} != df length {len(df)}"
            )
        raw_signals = raw_signals.reindex(df.index)
        sig_arr = _safe_signals(raw_signals)

        strategy_name = getattr(strategy, "name", type(strategy).__name__)

        trades, equity_list = self._simulator.run(df, sig_arr)

        capital = self.initial_capital
        if equity_list:
            equity_series = pd.Series(equity_list, index=df.index, dtype=float)
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
            max_dd       = 0.0
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
        pf_num        = sum(wins)
        pf_den        = abs(sum(losses))
        profit_factor = round(pf_num / pf_den, 4) if pf_den > 0 else (999.0 if pf_num > 0 else 0.0)

        total_charges = sum(
            self._cost_model.charges(t.entry_price * t.quantity, "BUY") +
            self._cost_model.charges(t.exit_price  * t.quantity, "SELL")
            for t in trades
        )

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
