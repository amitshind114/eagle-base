"""Backtesting API router.

FIX P0-003: Previous version called engine.run(df, signals, capital=req.capital)
which crashes because:
  1. engine.run() signature is run(self, df, strategy) — no 'signals' or 'capital' arg.
  2. capital is set via BacktestEngine(initial_capital=...), not run().
  3. signals must NOT be pre-computed outside the engine — strategy object is passed in.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backtesting.engine import BacktestEngine
from data.fetcher import DataFetcher
from strategies.sma_crossover import SmaCrossover
from strategies.ema_crossover import EmaCrossover
from strategies.rsi_mean_reversion import RsiMeanReversion
from strategies.macd_signal import MacdSignal
from core.exceptions import EagleBaseError

router  = APIRouter()
fetcher = DataFetcher()


class BacktestRequest(BaseModel):
    symbol:   str   = "RELIANCE.NS"
    period:   str   = "1y"
    strategy: str   = "SMA Crossover"
    capital:  float = 100_000.0
    fast:     int   = 20
    slow:     int   = 50


@router.post("/run")
def run_backtest(req: BacktestRequest):
    try:
        df = fetcher.fetch(req.symbol, period=req.period)

        strategy_map = {
            "SMA Crossover":      SmaCrossover(req.fast, req.slow),
            "EMA Crossover":      EmaCrossover(req.fast, req.slow),
            "RSI Mean Reversion": RsiMeanReversion(),
            "MACD Signal":        MacdSignal(),
        }
        strat = strategy_map.get(req.strategy)
        if strat is None:
            raise HTTPException(
                status_code=400, detail=f"Unknown strategy: {req.strategy}"
            )

        # FIX: create engine with capital; pass strategy object, not signals
        engine = BacktestEngine(symbol=req.symbol, initial_capital=req.capital)
        result = engine.run(df, strat)

        return {
            "symbol":               result.symbol,
            "strategy_name":        result.strategy_name,
            "total_return_pct":     result.total_return_pct,
            "buy_hold_return_pct":  result.buy_hold_return_pct,
            "sharpe_ratio":         result.sharpe_ratio,
            "max_drawdown_pct":     result.max_drawdown_pct,
            "win_rate_pct":         result.win_rate_pct,
            "total_trades":         result.total_trades,
            "profit_factor":        result.profit_factor,
            "final_capital":        result.final_capital,
        }
    except EagleBaseError as e:
        raise HTTPException(status_code=400, detail=str(e))
