"""FastAPI application entry point.

Registered routers:
  /api/data        — OHLCV data fetch
  /api/instruments — instrument search / master
  /api/backtest    — backtesting engine
  /api/risk        — position sizing / VaR
  /api/broker      — broker connection status (Angel One stub)
  /api/paper       — paper trading: signal, positions, snapshot, trades
  /api/live        — live trading: deploy, pause, stop, kill switches
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import data, instruments, backtesting, risk, broker
from .routers import paper as paper_router
from .routers import live  as live_router

app = FastAPI(
    title="Eagle-Base API",
    version="0.3.0",
    description="Algorithmic Research & Trading System API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router,            prefix="/api/data",        tags=["Data"])
app.include_router(instruments.router,     prefix="/api/instruments",  tags=["Instruments"])
app.include_router(backtesting.router,     prefix="/api/backtest",     tags=["Backtesting"])
app.include_router(risk.router,            prefix="/api/risk",         tags=["Risk"])
app.include_router(broker.router,          prefix="/api/broker",       tags=["Broker"])
app.include_router(paper_router.router,    prefix="/api/paper",        tags=["Paper Trading"])
app.include_router(live_router.router,     prefix="/api/live",         tags=["Live Trading"])


@app.get("/health")
def health():
    return {"status": "ok", "app": "Eagle-Base", "version": "0.3.0"}


@app.get("/api")
def api_index():
    """List all available API route prefixes."""
    return {
        "routes": [
            "/api/data",
            "/api/instruments",
            "/api/backtest",
            "/api/risk",
            "/api/broker",
            "/api/paper",
            "/api/live",
        ]
    }
