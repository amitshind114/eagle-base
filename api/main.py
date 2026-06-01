"""Eagle-Base FastAPI Application.

Main API entry point. Run with:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.logger import logger

app = FastAPI(
    title="Eagle-Base API",
    description="Algorithmic Research & Trading System API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    logger.info("Eagle-Base API starting up...")


@app.get("/")
async def root():
    return {"status": "ok", "system": "Eagle-Base", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "modules": {
            "data": "scaffold",
            "instruments": "scaffold",
            "backtesting": "scaffold",
            "strategies": "scaffold",
            "reporting": "scaffold",
            "risk": "scaffold",
            "paper": "scaffold",
            "ai": "scaffold",
            "derivatives": "scaffold",
            "live": "disabled",
        }
    }

# TODO: Add routers for each module as they are implemented in Phase 4
# from api.routers import data, backtesting, strategies, paper
# app.include_router(data.router, prefix="/data")
