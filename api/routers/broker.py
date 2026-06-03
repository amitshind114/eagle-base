"""Broker management API router.

Endpoints:
  GET  /broker/available   — list available broker adapters
  GET  /broker/active      — return currently active broker name
  POST /broker/switch      — switch active broker (BROKER env var override)
  GET  /broker/profile     — authenticated user profile from broker
  GET  /broker/funds       — available margin / funds
  GET  /broker/positions   — live positions
  GET  /broker/orders      — today's order book
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from brokers.registry import BrokerRegistry

router = APIRouter(prefix="/broker", tags=["broker"])

_active_broker_name: str = "angelone"


class SwitchBrokerRequest(BaseModel):
    broker: str


@router.get("/available")
def list_available_brokers() -> dict:
    return {"brokers": BrokerRegistry.available()}


@router.get("/active")
def get_active_broker() -> dict:
    return {"active": _active_broker_name}


@router.post("/switch")
def switch_broker(req: SwitchBrokerRequest) -> dict:
    global _active_broker_name  # noqa: PLW0603
    if req.broker not in BrokerRegistry.available():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown broker '{req.broker}'. "
                   f"Available: {BrokerRegistry.available()}",
        )
    _active_broker_name = req.broker
    return {"switched_to": _active_broker_name}


@router.get("/profile")
def get_profile() -> dict:
    try:
        broker = BrokerRegistry.get(_active_broker_name)
        if not broker.login():
            raise HTTPException(status_code=401, detail="Broker login failed")
        profile = broker.get_profile()
        return vars(profile)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/funds")
def get_funds() -> dict:
    try:
        broker = BrokerRegistry.get(_active_broker_name)
        if not broker.login():
            raise HTTPException(status_code=401, detail="Broker login failed")
        return broker.get_funds()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/positions")
def get_positions() -> list:
    try:
        broker = BrokerRegistry.get(_active_broker_name)
        if not broker.login():
            raise HTTPException(status_code=401, detail="Broker login failed")
        return [vars(p) for p in broker.get_positions()]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/orders")
def get_orders() -> list:
    try:
        broker = BrokerRegistry.get(_active_broker_name)
        if not broker.login():
            raise HTTPException(status_code=401, detail="Broker login failed")
        return broker.get_orders()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
