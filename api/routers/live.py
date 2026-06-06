"""Live trading API router.

Endpoints:
    GET  /api/live/status              — engine state + per-strategy info
    GET  /api/live/positions           — live open positions book
    GET  /api/live/orders              — today’s order log
    GET  /api/live/audit               — last N kill/deploy events
    POST /api/live/deploy              — deploy a strategy (PAPER|LIVE)
    POST /api/live/pause               — pause a specific strategy
    POST /api/live/stop                — stop a specific strategy
    POST /api/live/kill/strategies     — 🔴 stop ALL strategies
    POST /api/live/kill/orders         — 🔴 cancel ALL pending orders
    POST /api/live/kill/positions      — 🔴 square off ALL positions

Design notes:
    - All endpoints degrade gracefully when the live engine is unavailable.
    - Kill routes require confirm="CONFIRM" in the request body as an
      accidental-trigger guard. Wrong value → 400.
    - Audit log is an in-memory ring buffer (last 200 events). It persists
      for the lifetime of the FastAPI process.
    - Engine is lazily imported so the API starts cleanly even before the
      live module is fully wired.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, UTC
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

log = logging.getLogger("api.live")
router = APIRouter()

# ── Audit ring-buffer (in-memory, survives router reloads) ──────────────────
_AUDIT_MAX = 200
_audit_log: Deque[Dict[str, Any]] = deque(maxlen=_AUDIT_MAX)


def _audit(action: str, detail: Dict[str, Any]) -> None:
    """Append one event to the audit ring buffer."""
    _audit_log.appendleft({
        "ts":     datetime.now(UTC).isoformat(),
        "action": action,
        **detail,
    })


# ── Lazy engine singleton ────────────────────────────────────────────────────
_engine = None


def _get_engine():
    """Return the LiveEngine singleton, or None if not yet available."""
    global _engine
    if _engine is None:
        try:
            from live.engine import LiveEngine
            _engine = LiveEngine.instance()
        except Exception as exc:
            log.warning("[live router] LiveEngine not available: %s", exc)
    return _engine


# ── Request / Response models ───────────────────────────────────────────────

class DeployRequest(BaseModel):
    strategy_id:  str
    symbol:       str
    mode:         str  = "PAPER"      # "PAPER" | "LIVE"
    capital:      float = 100_000.0
    params:       Dict[str, Any] = {}

    @field_validator("mode")
    @classmethod
    def mode_must_be_valid(cls, v: str) -> str:
        v = v.upper()
        if v not in ("PAPER", "LIVE"):
            raise ValueError("mode must be PAPER or LIVE")
        return v


class StrategyActionRequest(BaseModel):
    strategy_id: str


class KillRequest(BaseModel):
    confirm: str  # must equal "CONFIRM" exactly

    @field_validator("confirm")
    @classmethod
    def must_confirm(cls, v: str) -> str:
        if v != "CONFIRM":
            raise ValueError('confirm must be the string "CONFIRM"')
        return v


# ── GET /status ─────────────────────────────────────────────────────────────

@router.get("/status")
def get_status():
    """Engine state + per-strategy deployment summary.

    Returns engine running/stopped state, uptime, and a list of every
    deployed strategy with its current mode (PAPER|LIVE) and state
    (RUNNING|PAUSED|STOPPED).
    """
    engine = _get_engine()
    if engine is None:
        return {
            "engine":     "unavailable",
            "strategies": [],
            "note":       "LiveEngine not loaded — start the live module first",
        }
    try:
        state      = getattr(engine, "state",      "UNKNOWN")
        uptime_s   = getattr(engine, "uptime_seconds", None)
        strategies = []
        runners    = getattr(engine, "runners", {}) or {}
        for sid, runner in runners.items():
            strategies.append({
                "strategy_id": sid,
                "symbol":      getattr(runner, "symbol",       ""),
                "mode":        getattr(runner, "mode",         "PAPER"),
                "state":       getattr(runner, "state",        "UNKNOWN"),
                "capital":     getattr(runner, "capital",      0),
                "deployed_at": str(getattr(runner, "deployed_at", "")),
            })
        return {
            "engine":     state,
            "uptime_s":   uptime_s,
            "strategies": strategies,
            "count":      len(strategies),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /positions ──────────────────────────────────────────────────────────

@router.get("/positions")
def get_positions():
    """Live open positions book across ALL deployed strategies.

    Aggregates positions from every active runner. Returns symbol,
    quantity, average cost, last price (best-effort yfinance), and
    unrealized PnL.
    """
    engine = _get_engine()
    if engine is None:
        return {"positions": [], "note": "LiveEngine unavailable"}
    try:
        positions: List[Dict[str, Any]] = []
        runners = getattr(engine, "runners", {}) or {}
        seen: Dict[str, Dict] = {}  # aggregate same symbol across runners

        for sid, runner in runners.items():
            portfolio = getattr(runner, "portfolio", None)
            if portfolio is None:
                continue
            pos_book = getattr(portfolio, "position_book",
                               getattr(portfolio, "open_positions", {}))
            items = pos_book.items() if isinstance(pos_book, dict) else (
                getattr(pos_book, "positions", {}).items()
            )
            for sym, pos in items:
                qty = getattr(pos, "quantity", 0) or getattr(pos, "qty", 0)
                if qty == 0:
                    continue
                avg = (
                    getattr(pos, "average_entry_price", None)
                    or getattr(pos, "avg_cost", None)
                    or getattr(pos, "average_price", 0)
                )
                ltp = avg
                try:
                    import yfinance as yf
                    hist = yf.Ticker(sym if "." in sym else f"{sym}.NS").history(period="1d")
                    if not hist.empty:
                        ltp = float(hist["Close"].iloc[-1])
                except Exception:
                    pass
                upnl    = (ltp - avg) * qty
                pnl_pct = ((ltp - avg) / avg * 100) if avg else 0.0
                entry   = {
                    "strategy_id":    sid,
                    "symbol":         sym,
                    "quantity":       qty,
                    "avg_cost":       round(avg, 2),
                    "last_price":     round(ltp, 2),
                    "unrealized_pnl": round(upnl, 2),
                    "pnl_pct":        round(pnl_pct, 2),
                }
                if sym in seen:
                    seen[sym]["quantity"]       += qty
                    seen[sym]["unrealized_pnl"] += round(upnl, 2)
                else:
                    seen[sym] = entry
                    positions.append(entry)

        return {"positions": positions, "count": len(positions)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /orders ──────────────────────────────────────────────────────────────

@router.get("/orders")
def get_orders(date_filter: Optional[str] = None):
    """Today’s order log across all deployed strategies.

    Pass ?date_filter=YYYY-MM-DD to fetch a specific day.
    Defaults to today.
    """
    engine = _get_engine()
    if engine is None:
        return {"orders": [], "note": "LiveEngine unavailable"}
    try:
        from datetime import date as _date
        filter_date = (
            _date.fromisoformat(date_filter) if date_filter else _date.today()
        )
        orders: List[Dict[str, Any]] = []
        runners = getattr(engine, "runners", {}) or {}

        for sid, runner in runners.items():
            order_book = getattr(runner, "order_book",
                          getattr(runner, "orders", []))
            raw_orders = (
                order_book if isinstance(order_book, list)
                else getattr(order_book, "orders", [])
            )
            for o in raw_orders:
                ts = getattr(o, "timestamp", getattr(o, "created_at", None))
                if ts and hasattr(ts, "date") and ts.date() != filter_date:
                    continue
                side_val = getattr(o, "side", "")
                if hasattr(side_val, "value"):
                    side_val = side_val.value
                status_val = getattr(o, "status", "")
                if hasattr(status_val, "value"):
                    status_val = status_val.value
                orders.append({
                    "strategy_id": sid,
                    "order_id":    getattr(o, "order_id",  getattr(o, "id", "")),
                    "symbol":      getattr(o, "symbol",    ""),
                    "side":        side_val,
                    "quantity":    getattr(o, "quantity",  getattr(o, "qty", 0)),
                    "price":       round(getattr(o, "price", 0), 2),
                    "status":      status_val,
                    "timestamp":   str(ts) if ts else "",
                })

        return {"orders": orders, "count": len(orders), "date": str(filter_date)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /audit ───────────────────────────────────────────────────────────────

@router.get("/audit")
def get_audit(limit: int = 50):
    """Last N kill/deploy/pause/stop events from the in-memory audit log.

    Events are newest-first. Max limit = 200.
    """
    limit = min(limit, _AUDIT_MAX)
    events = list(_audit_log)[:limit]
    return {"events": events, "count": len(events)}


# ── POST /deploy ───────────────────────────────────────────────────────────

@router.post("/deploy")
def deploy_strategy(req: DeployRequest):
    """Deploy a strategy to the live engine.

    mode="PAPER" runs in paper-only mode (no real orders).
    mode="LIVE"  routes orders to the configured broker.
    """
    engine = _get_engine()
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="LiveEngine not available — start the live module first",
        )
    try:
        engine.deploy(
            strategy_id=req.strategy_id,
            symbol=req.symbol,
            mode=req.mode,
            capital=req.capital,
            params=req.params,
        )
        _audit("DEPLOY", {
            "strategy_id": req.strategy_id,
            "symbol":      req.symbol,
            "mode":        req.mode,
            "capital":     req.capital,
        })
        log.info("[live/deploy] %s (%s) deployed on %s",
                 req.strategy_id, req.mode, req.symbol)
        return {
            "ok":          True,
            "strategy_id": req.strategy_id,
            "mode":        req.mode,
            "symbol":      req.symbol,
            "capital":     req.capital,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── POST /pause ─────────────────────────────────────────────────────────────

@router.post("/pause")
def pause_strategy(req: StrategyActionRequest):
    """Pause a specific strategy (stops new signals, holds open positions)."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="LiveEngine not available")
    try:
        engine.pause(req.strategy_id)
        _audit("PAUSE", {"strategy_id": req.strategy_id})
        log.info("[live/pause] %s paused", req.strategy_id)
        return {"ok": True, "strategy_id": req.strategy_id, "state": "PAUSED"}
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{req.strategy_id}' not found in engine",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── POST /stop ───────────────────────────────────────────────────────────────

@router.post("/stop")
def stop_strategy(req: StrategyActionRequest):
    """Stop a specific strategy and close all its open positions."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="LiveEngine not available")
    try:
        engine.stop(req.strategy_id)
        _audit("STOP", {"strategy_id": req.strategy_id})
        log.info("[live/stop] %s stopped", req.strategy_id)
        return {"ok": True, "strategy_id": req.strategy_id, "state": "STOPPED"}
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{req.strategy_id}' not found in engine",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── POST /kill/strategies ──────────────────────────────────────────────────

@router.post("/kill/strategies")
def kill_all_strategies(req: KillRequest):
    """🔴 EMERGENCY: Stop ALL deployed strategies immediately.

    Body must contain {"confirm": "CONFIRM"} or the request is rejected.
    Open positions are NOT closed — they remain in the portfolio.
    Use /kill/positions to square off.
    """
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="LiveEngine not available")
    try:
        stopped = getattr(engine, "kill_all_strategies",
                          getattr(engine, "stop_all", None))
        count = 0
        if stopped:
            result = stopped()
            count  = result if isinstance(result, int) else len(
                getattr(engine, "runners", {})
            )
        else:
            # Fallback: iterate runners and stop each
            runners = dict(getattr(engine, "runners", {}))
            for sid in runners:
                try:
                    engine.stop(sid)
                    count += 1
                except Exception:
                    pass

        _audit("KILL_STRATEGIES", {"stopped_count": count})
        log.warning("[live/kill/strategies] ALL strategies stopped (%d)", count)
        return {"ok": True, "action": "KILL_ALL_STRATEGIES", "stopped": count}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /kill/orders ──────────────────────────────────────────────────────────

@router.post("/kill/orders")
def kill_all_orders(req: KillRequest):
    """🔴 EMERGENCY: Cancel ALL pending/open orders across all strategies.

    Body must contain {"confirm": "CONFIRM"}.
    Calls broker cancel_all_orders() if available, otherwise iterates
    each runner’s order book and cancels individually.
    """
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="LiveEngine not available")
    try:
        cancelled = 0
        # Try engine-level cancel first
        cancel_all = getattr(engine, "cancel_all_orders", None)
        if cancel_all:
            result    = cancel_all()
            cancelled = result if isinstance(result, int) else 0
        else:
            # Fallback: iterate per-runner order books
            runners = getattr(engine, "runners", {}) or {}
            for sid, runner in runners.items():
                broker = getattr(runner, "broker", None)
                if broker and hasattr(broker, "cancel_all_orders"):
                    try:
                        r = broker.cancel_all_orders()
                        cancelled += r if isinstance(r, int) else 1
                    except Exception as e:
                        log.warning("[kill/orders] runner %s cancel failed: %s", sid, e)

        _audit("KILL_ORDERS", {"cancelled_count": cancelled})
        log.warning("[live/kill/orders] ALL orders cancelled (%d)", cancelled)
        return {"ok": True, "action": "KILL_ALL_ORDERS", "cancelled": cancelled}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /kill/positions ─────────────────────────────────────────────────────

@router.post("/kill/positions")
def kill_all_positions(req: KillRequest):
    """🔴 EMERGENCY: Square off ALL open positions at market price.

    Body must contain {"confirm": "CONFIRM"}.
    Iterates every runner’s portfolio, closes each open position at the
    last known price (or fetches live price via yfinance best-effort).
    """
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="LiveEngine not available")
    try:
        closed  = 0
        failed  = 0
        details: List[Dict[str, Any]] = []

        # Try engine-level square_off first
        square_off = getattr(engine, "square_off_all",
                     getattr(engine, "close_all_positions", None))
        if square_off:
            result = square_off()
            closed = result if isinstance(result, int) else 0
        else:
            # Fallback: close each position manually
            runners = getattr(engine, "runners", {}) or {}
            for sid, runner in runners.items():
                portfolio = getattr(runner, "portfolio", None)
                if portfolio is None:
                    continue
                pos_book = getattr(portfolio, "open_positions",
                           getattr(portfolio, "position_book", {}))
                items = pos_book.items() if isinstance(pos_book, dict) else (
                    getattr(pos_book, "positions", {}).items()
                )
                for sym, pos in list(items):
                    qty = getattr(pos, "quantity", 0) or getattr(pos, "qty", 0)
                    if qty == 0:
                        continue
                    # Best-effort live price
                    ltp = getattr(pos, "last_price", 0) or getattr(pos, "avg_cost", 0)
                    try:
                        import yfinance as yf
                        hist = yf.Ticker(
                            sym if "." in sym else f"{sym}.NS"
                        ).history(period="1d")
                        if not hist.empty:
                            ltp = float(hist["Close"].iloc[-1])
                    except Exception:
                        pass
                    try:
                        portfolio.close_position(sym, ltp)
                        closed += 1
                        details.append({"strategy_id": sid, "symbol": sym,
                                         "exit_price": round(ltp, 2), "qty": qty})
                    except Exception as e:
                        failed += 1
                        log.error("[kill/positions] close %s failed: %s", sym, e)

        _audit("KILL_POSITIONS", {"closed": closed, "failed": failed})
        log.warning(
            "[live/kill/positions] ALL positions squared off — closed=%d failed=%d",
            closed, failed,
        )
        return {
            "ok":      True,
            "action":  "KILL_ALL_POSITIONS",
            "closed":  closed,
            "failed":  failed,
            "details": details,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
