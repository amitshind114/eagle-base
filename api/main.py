"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import data, instruments, backtesting, risk

app = FastAPI(
    title="Eagle-Base API",
    version="0.1.0",
    description="Algorithmic Research & Trading System API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router, prefix="/api/data", tags=["Data"])
app.include_router(instruments.router, prefix="/api/instruments", tags=["Instruments"])
app.include_router(backtesting.router, prefix="/api/backtest", tags=["Backtesting"])
app.include_router(risk.router, prefix="/api/risk", tags=["Risk"])


@app.get("/health")
def health():
    return {"status": "ok", "app": "Eagle-Base", "version": "0.1.0"}
