"""FastAPI application entry point.

Authentication
--------------
Sensitive routers (/api/live, /api/paper) are protected by the
X-API-Key header dependency (see api/auth.py).  Set API_KEY in
your .env to enable enforcement; leave it empty for local dev.

Registered routers:
  /api/data        — OHLCV data fetch            (public)
  /api/instruments — instrument search / master  (public)
  /api/backtest    — backtesting engine          (public)
  /api/risk        — position sizing / VaR       (public)
  /api/broker      — broker connection status    (public)
  /api/paper       — paper trading               (🔒 X-API-Key)
  /api/live        — live trading                (🔒 X-API-Key)
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import require_api_key
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

# ── Public routes (no auth required) ──────────────────────────────────────
app.include_router(data.router,        prefix="/api/data",       tags=["Data"])
app.include_router(instruments.router, prefix="/api/instruments", tags=["Instruments"])
app.include_router(backtesting.router, prefix="/api/backtest",    tags=["Backtesting"])
app.include_router(risk.router,        prefix="/api/risk",        tags=["Risk"])
app.include_router(broker.router,      prefix="/api/broker",      tags=["Broker"])

# ── Protected routes (X-API-Key required when API_KEY is set) ─────────────
app.include_router(
    paper_router.router,
    prefix="/api/paper",
    tags=["Paper Trading"],
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    live_router.router,
    prefix="/api/live",
    tags=["Live Trading"],
    dependencies=[Depends(require_api_key)],
)


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
