"""Backtesting API router — Phase 07 fixed.

Fixes applied:
  P0: BacktestRequest now includes `interval` field.
  P0: engine = BacktestEngine(symbol, initial_capital, interval) — all three args.
  P0: result = engine.run(df, strat) — strategy object, not pre-computed signals.
  P1: equity_curve included in response so UI can plot the chart.
  P1: drawdown_series included for drawdown chart.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
    interval: str   = "1d"          # ← NEW: was missing, caused engine mismatch
    strategy: str   = "SMA Crossover"
    capital:  float = 100_000.0
    fast:     int   = Field(default=20, ge=2, le=200)
    slow:     int   = Field(default=50, ge=5, le=500)
    rsi_period:   int = Field(default=14, ge=2, le=50)
    rsi_oversold: int = Field(default=30, ge=10, le=50)
    rsi_overbought: int = Field(default=70, ge=50, le=90)
    macd_fast:    int = Field(default=12, ge=2, le=50)
    macd_slow:    int = Field(default=26, ge=5, le=100)
    macd_signal:  int = Field(default=9,  ge=2, le=30)


@router.post("/run")
def run_backtest(req: BacktestRequest):
    # Client-side guard: fast must be < slow for crossover strategies
    if req.strategy in ("SMA Crossover", "EMA Crossover") and req.fast >= req.slow:
        raise HTTPException(
            status_code=422,
            detail=f"fast ({req.fast}) must be less than slow ({req.slow})",
        )

    try:
        df = fetcher.fetch(req.symbol, period=req.period, interval=req.interval)

        strategy_map = {
            "SMA Crossover":      SmaCrossover(req.fast, req.slow),
            "EMA Crossover":      EmaCrossover(req.fast, req.slow),
            "RSI Mean Reversion": RsiMeanReversion(
                period=req.rsi_period,
                oversold=req.rsi_oversold,
                overbought=req.rsi_overbought,
            ),
            "MACD Signal": MacdSignal(
                fast=req.macd_fast,
                slow=req.macd_slow,
                signal=req.macd_signal,
            ),
        }
        strat = strategy_map.get(req.strategy)
        if strat is None:
            raise HTTPException(
                status_code=400, detail=f"Unknown strategy: {req.strategy}"
            )

        # FIX: pass interval so engine can annualise Sharpe correctly
        engine = BacktestEngine(
            symbol=req.symbol,
            initial_capital=req.capital,
            interval=req.interval,
        )
        result = engine.run(df, strat)

        # Equity curve for charting — convert pd.Series to list of {date, value}
        equity_curve = []
        drawdown_series = []
        if hasattr(result, "equity_curve") and result.equity_curve is not None:
            ec = result.equity_curve
            peak = ec.cummax()
            dd   = ((ec - peak) / peak * 100)
            for ts, val in ec.items():
                date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)
                equity_curve.append({"date": date_str, "value": round(float(val), 2)})
            for ts, val in dd.items():
                date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)
                drawdown_series.append({"date": date_str, "value": round(float(val), 4)})

        return {
            "symbol":               result.symbol,
            "strategy_name":        result.strategy_name,
            "interval":             req.interval,
            "total_return_pct":     round(result.total_return_pct, 4),
            "buy_hold_return_pct":  round(result.buy_hold_return_pct, 4),
            "sharpe_ratio":         round(result.sharpe_ratio, 4),
            "max_drawdown_pct":     round(result.max_drawdown_pct, 4),
            "win_rate_pct":         round(result.win_rate_pct, 4),
            "total_trades":         result.total_trades,
            "profit_factor":        round(result.profit_factor, 4),
            "final_capital":        round(result.final_capital, 2),
            "equity_curve":         equity_curve,
            "drawdown_series":      drawdown_series,
        }
    except EagleBaseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest error: {e}")


@router.get("/strategies")
def list_strategies():
    """Return available strategy names and their default parameters."""
    return {
        "strategies": [
            {
                "name": "SMA Crossover",
                "params": {"fast": 20, "slow": 50},
                "tags": ["trend", "daily"],
            },
            {
                "name": "EMA Crossover",
                "params": {"fast": 12, "slow": 26},
                "tags": ["trend", "daily"],
            },
            {
                "name": "RSI Mean Reversion",
                "params": {"rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70},
                "tags": ["mean_reversion"],
            },
            {
                "name": "MACD Signal",
                "params": {"macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
                "tags": ["momentum"],
            },
        ]
    }
