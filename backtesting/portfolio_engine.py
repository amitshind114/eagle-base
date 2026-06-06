"""PortfolioEngine — Phase 5.

Runs a strategy across multiple symbols simultaneously, allocates capital,
enforces position limits, tracks daily portfolio value, and produces a
combined equity curve.

Key rules enforced:
  - max_positions  : never hold more than N open positions at once
  - max_exposure_pct: single symbol never exceeds X% of total capital
  - Allocation: splits capital via AllocationMethod before each entry
  - Cash: tracked precisely — buying reduces cash, selling restores it
  - Error isolation: one symbol failure never aborts the whole run

Usage:
    from backtesting.portfolio_engine import PortfolioEngine
    from backtesting.allocation import AllocationMethod
    from backtesting.universe import load_universe
    from strategies.ema_crossover import EmaCrossover

    engine = PortfolioEngine()
    result = engine.run(
        strategy=EmaCrossover(),
        symbols=load_universe("NIFTY50"),
        total_capital=1_000_000,
        allocation=AllocationMethod.EQUAL_WEIGHT,
        max_positions=10,
        max_exposure_pct=20.0,
        from_date="2022-01-01",
        to_date="2024-12-31",
    )
    print(result.summary())
    print(result.monthly_returns())
"""

from __future__ import annotations

import traceback
from typing import Optional

import numpy as np
import pandas as pd

from core.logger import get_logger
from backtesting.allocation import AllocationMethod, allocate
from backtesting.portfolio_result import PortfolioResult
from backtesting.result import BacktestResult
from strategies.base import BaseStrategy

log = get_logger("backtesting.portfolio_engine")


class PortfolioEngine:
    """Simulate a multi-symbol portfolio backtest.

    Capital is shared across symbols. Positions are opened/closed by the
    strategy signals with allocation, exposure, and position-count limits.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        strategy: BaseStrategy,
        symbols: list[str],
        total_capital: float         = 1_000_000.0,
        allocation: AllocationMethod = AllocationMethod.EQUAL_WEIGHT,
        max_positions: int           = 10,
        max_exposure_pct: float      = 20.0,
        from_date: str               = "2022-01-01",
        to_date: str                 = "2024-12-31",
        interval: str                = "1d",
    ) -> PortfolioResult:
        """Run a portfolio backtest.

        Args:
            strategy        : A BaseStrategy instance.
            symbols         : List of .NS symbols to trade.
            total_capital   : Starting capital (shared across all positions).
            allocation      : How to split capital — AllocationMethod enum.
            max_positions   : Hard cap on simultaneous open positions.
            max_exposure_pct: Max % of total_capital in any single symbol.
            from_date       : Backtest start date (YYYY-MM-DD).
            to_date         : Backtest end date (YYYY-MM-DD).
            interval        : OHLCV bar interval (default '1d').

        Returns:
            PortfolioResult with equity curve, monthly returns, and per-symbol results.
        """
        log.info(
            f"[portfolio] START: strategy={strategy.name} symbols={len(symbols)} "
            f"capital={total_capital:,.0f} max_pos={max_positions}"
        )

        # Step 1: Fetch OHLCV for all symbols
        all_data = self._fetch_all(symbols, from_date, to_date, interval)
        if not all_data:
            log.error("[portfolio] No data fetched for any symbol.")
            return PortfolioResult(
                initial_capital=total_capital,
                strategy_name=strategy.name,
            )

        # Step 2: Build unified trading calendar (union of all date indices)
        all_dates = sorted(
            set().union(*[set(df.index) for df in all_data.values()])
        )

        # Step 3: Pre-compute signals for each symbol
        all_signals = self._compute_signals(strategy, all_data)

        # Step 4: Simulate day-by-day
        equity_curve, trade_rows, symbol_results = self._simulate(
            all_data=all_data,
            all_signals=all_signals,
            all_dates=all_dates,
            total_capital=total_capital,
            allocation=allocation,
            max_positions=max_positions,
            max_exposure_pct=max_exposure_pct,
        )

        # Step 5: Package result
        equity_series = pd.Series(equity_curve, index=pd.DatetimeIndex(all_dates[:len(equity_curve)]))
        trade_log     = pd.DataFrame(trade_rows) if trade_rows else pd.DataFrame()
        daily_pnl     = equity_series.diff().fillna(0)

        result = PortfolioResult(
            equity_curve=equity_series,
            symbol_results=symbol_results,
            trade_log=trade_log,
            daily_pnl=daily_pnl,
            initial_capital=total_capital,
            strategy_name=strategy.name,
            period=f"{from_date} → {to_date}",
        )

        log.info(
            f"[portfolio] DONE: return={result.total_return_pct:+.2f}% "
            f"sharpe={result.sharpe_ratio:.2f} mdd={result.max_drawdown_pct:.2f}%"
        )
        return result

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_all(
        self,
        symbols: list[str],
        from_date: str,
        to_date: str,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for all symbols. Silently skips symbols with no data."""
        result: dict[str, pd.DataFrame] = {}
        try:
            from data.manager import DataManager
            manager = DataManager()
        except Exception as exc:
            log.error(f"[portfolio] DataManager unavailable: {exc}")
            return result

        for symbol in symbols:
            try:
                df = manager.get_ohlcv(symbol, interval, from_date, to_date)
                if df is not None and not df.empty:
                    result[symbol] = df
                else:
                    log.debug(f"[portfolio] No data for {symbol}")
            except Exception as exc:
                log.warning(f"[portfolio] Fetch failed {symbol}: {exc}")

        log.info(f"[portfolio] Fetched data for {len(result)}/{len(symbols)} symbols")
        return result

    # ------------------------------------------------------------------
    # Signal computation
    # ------------------------------------------------------------------

    def _compute_signals(
        self,
        strategy: BaseStrategy,
        all_data: dict[str, pd.DataFrame],
    ) -> dict[str, pd.Series]:
        """Pre-compute generate_signals() for each symbol."""
        signals: dict[str, pd.Series] = {}
        for symbol, df in all_data.items():
            try:
                sig = strategy.generate_signals(df)
                signals[symbol] = sig
            except Exception as exc:
                log.warning(f"[portfolio] Signal error {symbol}: {exc}")
        return signals

    # ------------------------------------------------------------------
    # Day-by-day simulation
    # ------------------------------------------------------------------

    def _simulate(
        self,
        all_data: dict[str, pd.DataFrame],
        all_signals: dict[str, pd.Series],
        all_dates: list,
        total_capital: float,
        allocation: AllocationMethod,
        max_positions: int,
        max_exposure_pct: float,
    ) -> tuple[list[float], list[dict], dict[str, BacktestResult]]:
        """Core simulation loop.

        Returns:
            equity_curve  : list of daily portfolio values
            trade_rows    : list of trade dicts for the trade_log DataFrame
            symbol_results: per-symbol lightweight BacktestResult objects
        """
        cash: float                       = total_capital
        positions: dict[str, dict]        = {}  # symbol → {qty, entry_price, entry_date}
        equity_curve: list[float]         = []
        trade_rows: list[dict]            = []
        symbol_pnl: dict[str, float]      = {s: 0.0 for s in all_data}
        symbol_trades: dict[str, list]    = {s: [] for s in all_data}

        max_single_exposure = total_capital * (max_exposure_pct / 100)

        for date in all_dates:
            # --- current prices on this date ---
            prices: dict[str, float] = {}
            for symbol, df in all_data.items():
                if date in df.index:
                    prices[symbol] = float(df.loc[date, "Close"])

            # --- process signals ---
            for symbol in list(all_signals.keys()):
                if date not in all_data.get(symbol, pd.DataFrame()).index:
                    continue
                price = prices.get(symbol)
                if price is None or price <= 0:
                    continue

                sig_series = all_signals[symbol]
                if date not in sig_series.index:
                    continue
                signal = int(sig_series.loc[date])

                in_position = symbol in positions

                # --- EXIT: signal turned -1 or 0, we are long ---
                if in_position and signal <= 0:
                    pos        = positions.pop(symbol)
                    qty        = pos["qty"]
                    entry_px   = pos["entry_price"]
                    pnl        = (price - entry_px) * qty
                    cash       += price * qty
                    symbol_pnl[symbol] += pnl
                    trade_row = {
                        "symbol":      symbol,
                        "direction":   "LONG",
                        "entry_date":  str(pos["entry_date"]),
                        "exit_date":   str(date),
                        "entry_price": round(entry_px, 2),
                        "exit_price":  round(price, 2),
                        "qty":         qty,
                        "pnl":         round(pnl, 2),
                        "pnl_pct":     round((price / entry_px - 1) * 100, 2),
                    }
                    trade_rows.append(trade_row)
                    symbol_trades[symbol].append(trade_row)

                # --- ENTRY: signal is 1, not already in position ---
                elif not in_position and signal == 1:
                    # Check position count limit
                    if len(positions) >= max_positions:
                        continue

                    # Compute allocation for this symbol
                    active_syms  = [symbol]  # allocate for this entry only
                    alloc        = allocate(
                        method=allocation,
                        symbols=active_syms,
                        capital=min(cash, max_single_exposure),
                    )
                    alloc_capital = alloc.get(symbol, 0.0)

                    if alloc_capital <= 0 or cash < alloc_capital:
                        continue

                    qty = max(1, int(alloc_capital // price))
                    cost = qty * price
                    if cost > cash:
                        continue

                    cash -= cost
                    positions[symbol] = {
                        "qty":         qty,
                        "entry_price": price,
                        "entry_date":  date,
                    }

            # --- mark-to-market: equity = cash + open position values ---
            open_value = sum(
                positions[s]["qty"] * prices.get(s, positions[s]["entry_price"])
                for s in positions
            )
            equity_curve.append(cash + open_value)

        # --- close any remaining open positions at last price ---
        for symbol, pos in list(positions.items()):
            last_price = None
            df = all_data.get(symbol)
            if df is not None and not df.empty:
                last_price = float(df["Close"].iloc[-1])
            if last_price:
                pnl   = (last_price - pos["entry_price"]) * pos["qty"]
                cash += last_price * pos["qty"]
                symbol_pnl[symbol] += pnl

        # --- build per-symbol BacktestResult stubs ---
        symbol_results: dict[str, BacktestResult] = {}
        for symbol in all_data:
            from backtesting.result import BacktestResult as BR
            r = BR(
                symbol=symbol,
                strategy_name="portfolio:" + symbol,
                initial_capital=total_capital / max(len(all_data), 1),
                metrics={"pnl": symbol_pnl.get(symbol, 0.0)},
            )
            symbol_results[symbol] = r

        return equity_curve, trade_rows, symbol_results
