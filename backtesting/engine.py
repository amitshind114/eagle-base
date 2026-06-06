"""Core backtesting engine — runs a strategy on historical OHLCV data.

Accurate NSE cost model:
    - Slippage  : configurable fill-price offset (default 0.05%)
    - Brokerage : flat ₹20 per executed order (Zerodha MIS default)
    - STT       : 0.025% on sell-side turnover
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

# ── NSE charge constants ──────────────────────────────────────────────────
_BROKERAGE_FLAT  = 20.0        # ₹20 per order (intraday)
_STT_SELL        = 0.00025     # 0.025% on sell turnover
_EXCHANGE_CHARGE = 0.0000335   # NSE txn charge
_SEBI_CHARGE     = 0.000001    # ₹10/crore
_STAMP_BUY       = 0.00003     # 0.003% on buy turnover
_GST             = 0.18        # 18% on brokerage + exchange


def _nse_charges(turnover: float, side: str) -> float:
    """Total NSE charges in INR for one leg of a trade."""
    brokerage = _BROKERAGE_FLAT
    stt       = turnover * _STT_SELL  if side == "SELL" else 0.0
    exchange  = turnover * _EXCHANGE_CHARGE
    sebi      = turnover * _SEBI_CHARGE
    stamp     = turnover * _STAMP_BUY if side == "BUY"  else 0.0
    gst       = (brokerage + exchange) * _GST
    return brokerage + stt + exchange + sebi + stamp + gst


class BacktestEngine:
    """Event-driven backtesting engine with accurate NSE cost simulation."""

    def __init__(
        self,
        symbol: str = "",
        initial_capital: float = 100_000.0,
        commission_pct: float = 0.0,      # legacy param — kept for API compat, ignored
        slippage_pct: float = 0.0005,     # 0.05% default fill slippage
    ) -> None:
        self.symbol          = symbol
        self.initial_capital = initial_capital
        self.slippage_pct    = slippage_pct

    def run(self, df: pd.DataFrame, strategy: "BaseStrategy") -> BacktestResult:
        """Run strategy on OHLCV df and return a fully populated BacktestResult.

        Args:
            df       : DataFrame with columns Open/High/Low/Close/Volume and DatetimeIndex.
            strategy : A BaseStrategy instance. engine calls strategy.generate_signals(df).

        Returns:
            BacktestResult with equity curve, trade log, and all scalar metrics.
        """
        if df is None or df.empty or len(df) < 10:
            raise InsufficientDataError("Need at least 10 bars to backtest")

        df = df.copy()
        signals: pd.Series = strategy.generate_signals(df)

        if len(signals) != len(df):
            raise BacktestError("signals length must match df length")

        strategy_name = getattr(strategy, "name", type(strategy).__name__)

        capital    = self.initial_capital
        cash       = capital
        position   = 0        # shares held
        avg_cost   = 0.0
        entry_date = None
        entry_price_fill = 0.0
        equity     = []
        trades: list[Trade] = []
        total_charges = 0.0

        for i, (ts, row) in enumerate(df.iterrows()):
            sig   = int(signals.iloc[i])
            close = float(row["Close"])

            # ─ Entry: BUY signal and flat ─────────────────────────────────
            if sig == 1 and position == 0 and close > 0:
                fill_price = close * (1 + self.slippage_pct)
                qty        = int(cash * 0.95 / fill_price)   # use 95% of cash
                if qty > 0:
                    turnover          = fill_price * qty
                    charges           = _nse_charges(turnover, "BUY")
                    cash             -= (turnover + charges)
                    avg_cost          = fill_price
                    entry_price_fill  = fill_price
                    entry_date        = ts
                    position          = qty
                    total_charges    += charges

            # ─ Exit: SELL signal while in position ────────────────────────
            elif sig == -1 and position > 0 and close > 0:
                fill_price  = close * (1 - self.slippage_pct)
                turnover    = fill_price * position
                charges     = _nse_charges(turnover, "SELL")
                gross_pnl   = (fill_price - avg_cost) * position
                net_pnl     = gross_pnl - charges
                cost_basis  = avg_cost * position
                pnl_pct     = net_pnl / cost_basis * 100 if cost_basis > 0 else 0.0
                cash       += turnover - charges
                total_charges += charges

                trades.append(Trade(
                    symbol       = self.symbol,
                    direction    = "LONG",
                    entry_date   = entry_date,
                    exit_date    = ts,
                    entry_price  = round(entry_price_fill, 4),
                    exit_price   = round(fill_price, 4),
                    quantity     = position,
                    pnl          = round(net_pnl, 4),
                    pnl_pct      = round(pnl_pct, 4),
                    exit_reason  = "SIGNAL",
                ))

                position  = 0
                avg_cost  = 0.0

            mark_to_market = position * close
            equity.append(cash + mark_to_market)

        # ─ Force-close open position at last bar ──────────────────────────
        if position > 0:
            last_close   = float(df["Close"].iloc[-1])
            fill_price   = last_close * (1 - self.slippage_pct)
            turnover     = fill_price * position
            charges      = _nse_charges(turnover, "SELL")
            net_pnl      = (fill_price - avg_cost) * position - charges
            cost_basis   = avg_cost * position
            pnl_pct      = net_pnl / cost_basis * 100 if cost_basis > 0 else 0.0
            cash        += turnover - charges
            # Correct the final equity entry to reflect closed cash (no mark-to-market)
            equity[-1]   = cash

            trades.append(Trade(
                symbol       = self.symbol,
                direction    = "LONG",
                entry_date   = entry_date,
                exit_date    = df.index[-1],
                entry_price  = round(entry_price_fill, 4),
                exit_price   = round(fill_price, 4),
                quantity     = position,
                pnl          = round(net_pnl, 4),
                pnl_pct      = round(pnl_pct, 4),
                exit_reason  = "END_OF_DATA",
            ))

        equity_series = pd.Series(equity, index=df.index)
        bh_series     = capital * (1 + df["Close"].pct_change().fillna(0)).cumprod()
        dd_series     = (equity_series / equity_series.cummax()) - 1   # negative fractions

        final_cap    = float(equity_series.iloc[-1])
        total_return = (final_cap - capital) / capital * 100
        bh_return    = (float(bh_series.iloc[-1]) - capital) / capital * 100
        max_dd       = float(dd_series.min() * 100)   # negative (e.g. -15.3)

        strat_rets = equity_series.pct_change().fillna(0)
        std        = float(strat_rets.std())
        sharpe     = float(strat_rets.mean() / std * np.sqrt(252)) if std > 0 else 0.0

        trades_pnl = [t.pnl for t in trades]
        wins       = [p for p in trades_pnl if p > 0]
        losses     = [p for p in trades_pnl if p <= 0]
        n_trades   = len(trades_pnl)
        win_rate   = len(wins) / n_trades * 100 if n_trades else 0.0
        avg_win    = sum(wins) / len(wins) / capital * 100 if wins else 0.0
        avg_loss   = sum(losses) / len(losses) / capital * 100 if losses else 0.0
        pf_num     = sum(wins)
        pf_den     = abs(sum(losses))
        # FIX P1: all-win strategy must NOT return 0.0
        if pf_den > 0:
            profit_factor = round(pf_num / pf_den, 4)
        elif pf_num > 0:
            profit_factor = 999.0   # all wins, no losses
        else:
            profit_factor = 0.0     # no trades or all-loss

        log.info(
            f"{self.symbol} | Return={total_return:.1f}% Sharpe={sharpe:.2f} "
            f"MaxDD={max_dd:.1f}% WR={win_rate:.1f}% Trades={n_trades} "
            f"Charges=\u20b9{total_charges:,.0f}"
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
            max_drawdown_pct    = round(max_dd, 2),   # negative
            win_rate_pct        = round(win_rate, 2),
            total_trades        = n_trades,
            profit_factor       = profit_factor,
            avg_win_pct         = round(avg_win, 3),
            avg_loss_pct        = round(avg_loss, 3),
            final_capital       = round(final_cap, 2),
        )
