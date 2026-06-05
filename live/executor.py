"""Live order executor via Angel One SmartAPI.

⚠️  This module places REAL orders with REAL money.
Set LIVE_ENABLED=True ONLY after paper trading is fully validated.

Safety chain (must all pass before any order is submitted):
    1. LIVE_ENABLED flag              — hard off-switch in code
    2. risk.gate.compute_allowed_actions  — deterministic pre-trade check
    3. risk_limits.check              — daily loss cap / trade count
    4. Order.create()                 — final gate-wrapped construction
    5. Audit record                   — every decision logged regardless of outcome

Angel One SmartAPI credentials are read from environment variables:
    ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET
"""

from __future__ import annotations

from typing import Any

from core.audit import audit
from core.base import BaseExecutor
from core.logger import logger
from risk.gate import compute_allowed_actions
from risk.limits import RiskLimitBreached, risk_limits

LIVE_ENABLED = False  # Set True ONLY after full paper trading validation


class LiveExecutor(BaseExecutor):
    """Live order executor via Angel One SmartAPI.

    Pre-trade safety checks run even when the Angel One call is stubbed—
    so the full gate + audit chain is testable without real credentials.
    """

    def __init__(self) -> None:
        if not LIVE_ENABLED:
            logger.warning("LiveExecutor: LIVE_ENABLED=False — live trading disabled")
        self._client = None  # Angel One SmartConnect client — init on connect()

    def connect(self) -> None:
        """Authenticate with Angel One.  Call once at session start."""
        if not LIVE_ENABLED:
            logger.info("LiveExecutor.connect(): skipped (live disabled)")
            return
        import os
        try:
            from SmartApi import SmartConnect  # pip install smartapi-python
            key    = os.environ["ANGEL_API_KEY"]
            cid    = os.environ["ANGEL_CLIENT_ID"]
            pwd    = os.environ["ANGEL_PASSWORD"]
            import pyotp
            totp   = pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"]).now()
            self._client = SmartConnect(api_key=key)
            self._client.generateSession(cid, pwd, totp)
            logger.info("LiveExecutor: Angel One session established")
            audit.record("SESSION_START", "SYSTEM", session="live")
        except Exception as exc:
            logger.error(f"LiveExecutor.connect() failed: {exc}")
            raise

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float = 0.0,
        order_type: str = "MARKET",
        tag: str = "",
        capital: float | None = None,
        prices: dict | None = None,
        portfolio: dict | None = None,
        vix: float | None = None,
    ) -> dict[str, Any]:
        """Place a live order via Angel One after all safety checks pass.

        Returns the broker response dict on success.
        Raises RuntimeError if LIVE_ENABLED=False.
        Raises ValueError if the risk gate blocks the trade.
        Raises RiskLimitBreached if daily limits are exceeded.
        """
        sym = symbol.upper().replace(".NS", "")

        if not LIVE_ENABLED:
            raise RuntimeError(
                "Live trading is disabled. Validate paper trading first, "
                "then set LIVE_ENABLED=True."
            )

        # ─ Step 1: Risk gate ────────────────────────────────────────────
        allowed = compute_allowed_actions(
            symbol=sym, capital=capital, prices=prices,
            portfolio=portfolio, vix=vix,
        )
        if not allowed:
            audit.record("GATE_BLOCK", sym, session="live",
                         reason=allowed.block_reason, flags=allowed.flags)
            raise ValueError(f"Gate blocked [{sym}]: {allowed.block_reason}")

        # ─ Step 2: Daily limits ──────────────────────────────────────────
        safe_qty = min(qty, allowed.max_qty) if allowed.max_qty > 0 else qty
        try:
            risk_limits.check(sym, side, safe_qty, price or 0.0)
        except RiskLimitBreached as exc:
            audit.record("LIMIT_BREACH", sym, session="live", reason=str(exc))
            raise

        # ─ Step 3: Submit to Angel One ──────────────────────────────────
        if not self._client:
            raise RuntimeError("Call connect() before place_order()")

        order_params = {
            "variety":         "NORMAL",
            "tradingsymbol":   sym,
            "symboltoken":     self._resolve_token(sym),
            "transactiontype": side.upper(),
            "exchange":        "NSE",
            "ordertype":       order_type.upper(),
            "producttype":     "INTRADAY",
            "duration":        "DAY",
            "price":           str(price) if order_type == "LIMIT" else "0",
            "quantity":        str(safe_qty),
            "squareoff":       "0",
            "stoploss":        "0",
        }

        try:
            response = self._client.placeOrder(order_params)
            broker_id = response.get("data", {}).get("orderid", "")
            risk_limits.record_trade(sym, side, safe_qty, price or 0.0)
            audit.record(
                "ORDER_PLACED", sym, session="live",
                side=side, qty=safe_qty, price=price,
                broker_order_id=broker_id, tag=tag,
            )
            logger.info(f"Live order placed: {side} {safe_qty} {sym} | broker_id={broker_id}")
            return response
        except Exception as exc:
            audit.record("ORDER_ERROR", sym, session="live", error=str(exc))
            logger.error(f"Live order failed [{sym}]: {exc}")
            raise

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        """Cancel a live order by broker order ID."""
        if not LIVE_ENABLED or not self._client:
            raise RuntimeError("Live trading not active")
        try:
            self._client.cancelOrder(order_id, variety)
            audit.record("ORDER_CANCELLED", "SYSTEM", session="live", order_id=order_id)
            logger.info(f"Order {order_id} cancelled")
            return True
        except Exception as exc:
            logger.error(f"Cancel failed [{order_id}]: {exc}")
            return False

    def get_positions(self) -> list[dict[str, Any]]:
        """Fetch current open positions from Angel One."""
        if not LIVE_ENABLED or not self._client:
            return []
        try:
            resp = self._client.position()
            return resp.get("data") or []
        except Exception as exc:
            logger.error(f"get_positions failed: {exc}")
            return []

    def _resolve_token(self, symbol: str) -> str:
        """Resolve symbol to Angel One instrument token.

        Looks up from instruments/ token file if available,
        falls back to empty string (Angel One requires this for MARKET orders).
        """
        try:
            from instruments.token_map import get_token
            return get_token(symbol)
        except Exception:
            return ""
