"""Paper trading API router — Phase 07 NEW.

Endpoints:
  POST /api/paper/signal    — fire a signal → paper trade executed
  GET  /api/paper/positions — all open positions
  GET  /api/paper/snapshot  — full portfolio snapshot (cash, positions, pnl)
  GET  /api/paper/trades    — today's trade log
  GET  /api/paper/status    — portfolio health check

The router lazily imports PaperPortfolio so the API starts even if
the paper module has import errors (provides a degraded response).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger("api.paper")
router = APIRouter()

# ── Lazy portfolio singleton ─────────────────────────────────────────────────
_portfolio = None

def _get_portfolio():
    global _portfolio
    if _portfolio is None:
        try:
            from paper.portfolio import PaperPortfolio
            _portfolio = PaperPortfolio()
            try:
                _portfolio.restore()
            except Exception:
                pass  # fresh portfolio if restore fails
        except ImportError as e:
            log.warning("[paper router] PaperPortfolio not available: %s", e)
    return _portfolio


# ── Request / Response models ────────────────────────────────────────────────

class SignalRequest(BaseModel):
    symbol:    str
    signal:    int          # 1 = BUY, -1 = SELL, 0 = HOLD
    price:     float
    quantity:  int   = 1
    strategy:  str   = "manual"


class PositionOut(BaseModel):
    symbol:         str
    quantity:       int
    avg_cost:       float
    current_price:  float
    unrealized_pnl: float
    pnl_pct:        float


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/signal")
def fire_signal(req: SignalRequest):
    """Execute a paper trade from a strategy signal.

    signal=1  → BUY  qty shares at price
    signal=-1 → SELL qty shares at price
    signal=0  → HOLD (no-op, returns current position)
    """
    portfolio = _get_portfolio()
    if portfolio is None:
        raise HTTPException(status_code=503, detail="Paper portfolio not available")

    if req.signal == 0:
        return {"action": "HOLD", "symbol": req.symbol, "price": req.price}

    side = "BUY" if req.signal == 1 else "SELL"
    try:
        portfolio.on_signal(
            signal=req.signal,
            symbol=req.symbol,
            price=req.price,
            qty=req.quantity,
        )
        try:
            portfolio.persist()
        except Exception as pe:
            log.warning("[paper router] persist failed: %s", pe)

        return {
            "action":   side,
            "symbol":   req.symbol,
            "price":    req.price,
            "quantity": req.quantity,
            "strategy": req.strategy,
            "cash":     round(portfolio.cash, 2),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/positions")
def get_positions():
    """Return all open positions with live unrealized PnL."""
    portfolio = _get_portfolio()
    if portfolio is None:
        return {"positions": [], "note": "paper portfolio unavailable"}

    try:
        positions = []
        pos_book = portfolio.position_book
        for sym, pos in pos_book.positions.items():
            qty = getattr(pos, "quantity", 0) or getattr(pos, "qty", 0)
            if qty == 0:
                continue
            avg = getattr(pos, "avg_cost", 0) or getattr(pos, "average_price", 0)
            # Fetch live price via yfinance (best-effort)
            ltp = avg  # fallback to avg if fetch fails
            try:
                import yfinance as yf
                hist = yf.Ticker(sym).history(period="1d")
                if not hist.empty:
                    ltp = float(hist["Close"].iloc[-1])
            except Exception:
                pass
            upnl = (ltp - avg) * qty
            pnl_pct = ((ltp - avg) / avg * 100) if avg else 0
            positions.append({
                "symbol":         sym,
                "quantity":       qty,
                "avg_cost":       round(avg, 2),
                "current_price":  round(ltp, 2),
                "unrealized_pnl": round(upnl, 2),
                "pnl_pct":        round(pnl_pct, 2),
            })
        return {"positions": positions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/snapshot")
def get_snapshot():
    """Full portfolio snapshot: cash + positions + total value + daily PnL."""
    portfolio = _get_portfolio()
    if portfolio is None:
        return {
            "status": "unavailable",
            "cash": 0,
            "positions_value": 0,
            "total_value": 0,
            "daily_pnl": 0,
            "positions": [],
        }

    try:
        snap = portfolio.snapshot()
        # snapshot() returns a PortfolioSnapshot dataclass or dict
        if hasattr(snap, "__dict__"):
            snap = snap.__dict__
        return snap
    except Exception as e:
        # Fallback: build snapshot manually
        try:
            cash = round(portfolio.cash, 2)
            positions_resp = get_positions()["positions"]
            pos_value = sum(p["current_price"] * p["quantity"] for p in positions_resp)
            return {
                "status":          "ok",
                "cash":            cash,
                "positions_value": round(pos_value, 2),
                "total_value":     round(cash + pos_value, 2),
                "daily_pnl":       round(portfolio.daily_pnl(), 2) if hasattr(portfolio, "daily_pnl") else 0,
                "positions":       positions_resp,
                "error":           str(e),
            }
        except Exception as e2:
            raise HTTPException(status_code=500, detail=str(e2))


@router.get("/trades")
def get_trades(date_filter: Optional[str] = None):
    """Return trade log. Pass ?date_filter=YYYY-MM-DD to filter by day.
    Defaults to today's trades.
    """
    portfolio = _get_portfolio()
    if portfolio is None:
        return {"trades": [], "note": "paper portfolio unavailable"}

    try:
        trade_book = portfolio.trade_book
        if date_filter:
            filter_date = date.fromisoformat(date_filter)
            trades = [
                t for t in trade_book.trades
                if hasattr(t, "timestamp") and getattr(t.timestamp, "date", lambda: None)() == filter_date
            ]
        else:
            trades = trade_book.today() if hasattr(trade_book, "today") else trade_book.trades

        trade_list = []
        for t in trades:
            side_val = t.side.value if hasattr(t.side, "value") else str(t.side)
            trade_list.append({
                "trade_id":  getattr(t, "trade_id",  ""),
                "symbol":    getattr(t, "symbol",    ""),
                "side":      side_val,
                "quantity":  getattr(t, "quantity",  getattr(t, "qty", 0)),
                "price":     round(getattr(t, "price", 0), 2),
                "pnl":       round(getattr(t, "pnl",   0), 2),
                "timestamp": str(getattr(t, "timestamp", "")),
            })
        return {"trades": trade_list, "count": len(trade_list)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def paper_status():
    """Health check — returns whether paper portfolio is available."""
    portfolio = _get_portfolio()
    if portfolio is None:
        return {"status": "unavailable", "message": "PaperPortfolio could not be loaded"}
    try:
        cash = round(portfolio.cash, 2)
        n_positions = len([
            sym for sym, pos in portfolio.position_book.positions.items()
            if (getattr(pos, "quantity", 0) or getattr(pos, "qty", 0)) > 0
        ])
        return {
            "status":      "ok",
            "cash":        cash,
            "n_positions": n_positions,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
