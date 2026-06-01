"""Backtest Engine — Priority 3.

Bar-by-bar simulation engine.
Iterates over OHLCV data, calls strategy.on_bar() each step,
collects signals, executes simulated trades, builds equity curve.

Usage:
    engine = BacktestEngine(symbol="RELIANCE.NS", initial_capital=100000)
    result = engine.run(df, strategy)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from backtesting.result import BacktestResult, Trade
from backtesting.metrics import MetricsCalculator
from core.logger import logger

if TYPE_CHECKING:
    from strategies.base import BaseStrategy


class BacktestEngine:
    """Bar-by-bar backtesting engine with long-only simulation."""

    def __init__(
        self,
        symbol: str = "UNKNOWN",
        initial_capital: float = 100_000.0,
        commission_pct: float = 0.0003,   # 0.03% per leg (typical NSE)
        slippage_pct: float = 0.0001,     # 0.01% slippage
        position_size_pct: float = 0.95,  # Use 95% of capital per trade
    ):
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.position_size_pct = position_size_pct
        self._metrics = MetricsCalculator()

    def run(self, df: pd.DataFrame, strategy: "BaseStrategy") -> BacktestResult:
        """Run backtest over OHLCV DataFrame.

        Args:
            df:       OHLCV DataFrame with columns Open, High, Low, Close, Volume
            strategy: Any strategy inheriting BaseStrategy

        Returns:
            BacktestResult with trades, equity curve, metrics
        """
        logger.info(f"[engine] Starting backtest: {strategy.name} on {self.symbol} ({len(df)} bars)")

        result = BacktestResult(
            symbol=self.symbol,
            strategy_name=strategy.name,
            initial_capital=self.initial_capital,
        )

        capital = self.initial_capital
        position = 0       # shares held
        entry_price = 0.0
        entry_date = ""
        equity_curve = [capital]

        strategy.reset()

        for i in range(len(df)):
            bar = df.iloc[i]
            close = float(bar["Close"])
            date_str = str(df.index[i])[:10]

            # Feed bar to strategy
            signal = strategy.on_bar(df.iloc[: i + 1])

            # --- ENTRY ---
            if signal == "BUY" and position == 0:
                entry_px = close * (1 + self.slippage_pct)
                commission = entry_px * self.commission_pct
                qty = int((capital * self.position_size_pct) / (entry_px + commission))
                if qty > 0:
                    position = qty
                    entry_price = entry_px
                    entry_date = date_str
                    capital -= qty * (entry_px + commission)
                    logger.debug(f"[engine] BUY  {qty} @ {entry_px:.2f} on {date_str}")

            # --- EXIT ---
            elif signal == "SELL" and position > 0:
                exit_px = close * (1 - self.slippage_pct)
                commission = exit_px * self.commission_pct
                proceeds = position * (exit_px - commission)
                pnl = proceeds - position * entry_price
                pnl_pct = pnl / (position * entry_price) * 100 if entry_price else 0

                result.trades.append(Trade(
                    symbol=self.symbol,
                    direction="LONG",
                    entry_date=entry_date,
                    exit_date=date_str,
                    entry_price=entry_price,
                    exit_price=exit_px,
                    quantity=position,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    exit_reason="SIGNAL",
                ))
                capital += proceeds
                logger.debug(f"[engine] SELL {position} @ {exit_px:.2f} on {date_str} | PnL: {pnl:.2f}")
                position = 0
                entry_price = 0.0

            # Mark-to-market equity
            mtm = capital + (position * close)
            equity_curve.append(mtm)

        # Force-close open position at end of data
        if position > 0:
            last_close = float(df.iloc[-1]["Close"])
            exit_px = last_close * (1 - self.slippage_pct)
            commission = exit_px * self.commission_pct
            proceeds = position * (exit_px - commission)
            pnl = proceeds - position * entry_price
            pnl_pct = pnl / (position * entry_price) * 100 if entry_price else 0
            result.trades.append(Trade(
                symbol=self.symbol,
                direction="LONG",
                entry_date=entry_date,
                exit_date=str(df.index[-1])[:10],
                entry_price=entry_price,
                exit_price=exit_px,
                quantity=position,
                pnl=pnl,
                pnl_pct=pnl_pct,
                exit_reason="END_OF_DATA",
            ))
            capital += proceeds
            equity_curve[-1] = capital

        result.equity_curve = equity_curve
        result.metrics = self._metrics.compute(result)

        logger.info(f"[engine] Done — {result.total_trades} trades | Return: {result.total_return_pct:.2f}%")
        return result
