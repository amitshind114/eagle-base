"""Angel One SmartAPI broker adapter.

Required env vars:
    ANGELONE_API_KEY
    ANGELONE_CLIENT_ID
    ANGELONE_PASSWORD
    ANGELONE_TOTP_SECRET

Dependency: pip install smartapi-python pyotp

Fixes applied
-------------
- TOTP generated at login time via pyotp.TOTP().now() — never stored.
- JWT refresh: every API call checks expiry and refreshes 5 minutes early.
- Token passed to place_order comes from instruments.angel_master.resolve_token,
  not from the caller blindly (call sites must supply it).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable

from brokers.base import BrokerBase
from brokers.models import BrokerOrder, BrokerPosition, BrokerProfile
from core.logger import get_logger

logger = get_logger(__name__)

# JWT is valid for ~24 h; refresh 5 minutes before expiry
_JWT_TTL_HOURS = 23
_REFRESH_BUFFER = timedelta(minutes=5)


def _ensure_connected(method: Callable) -> Callable:
    """Decorator: refresh JWT if it is close to expiry before every API call."""
    @wraps(method)
    def wrapper(self: "AngelOneBroker", *args: Any, **kwargs: Any) -> Any:
        if self._connected and self._jwt_expiry is not None:
            if datetime.now(tz=timezone.utc) >= self._jwt_expiry - _REFRESH_BUFFER:
                logger.info("[angelone] JWT near expiry — refreshing token.")
                self._refresh_token()
        return method(self, *args, **kwargs)
    return wrapper


class AngelOneBroker(BrokerBase):
    name = "angelone"

    def __init__(self) -> None:
        self._api_key      = os.getenv("ANGELONE_API_KEY", "")
        self._client_id    = os.getenv("ANGELONE_CLIENT_ID", "")
        self._password     = os.getenv("ANGELONE_PASSWORD", "")
        self._totp_secret  = os.getenv("ANGELONE_TOTP_SECRET", "")
        self._smart_api: Any       = None
        self._auth_token: str      = ""
        self._refresh_tkn: str     = ""
        self._jwt_expiry: datetime | None = None
        self._connected: bool      = False

    # ── Auth ──────────────────────────────────────────────────────────────

    def login(self) -> bool:
        """Login to Angel One. Generates a fresh TOTP at call time."""
        try:
            import pyotp
            from SmartApi import SmartConnect  # type: ignore[import]

            # TOTP must be generated at the exact moment of the login call.
            totp_value = pyotp.TOTP(self._totp_secret).now()

            self._smart_api = SmartConnect(api_key=self._api_key)
            data = self._smart_api.generateSession(
                self._client_id, self._password, totp_value
            )

            if data.get("status"):
                self._auth_token  = data["data"]["jwtToken"]
                self._refresh_tkn = data["data"].get("refreshToken", "")
                self._jwt_expiry  = (
                    datetime.now(tz=timezone.utc)
                    + timedelta(hours=_JWT_TTL_HOURS)
                )
                self._connected = True
                logger.info("[angelone] Login successful for %s", self._client_id)
                return True

            logger.error("[angelone] Login failed: %s", data.get("message"))
            return False

        except Exception as exc:
            logger.exception("[angelone] Login error: %s", exc)
            return False

    def _refresh_token(self) -> bool:
        """Silently refresh JWT using the stored refresh token."""
        if not self._smart_api or not self._refresh_tkn:
            logger.warning("[angelone] Cannot refresh — no refresh token. Re-login required.")
            return self.login()
        try:
            resp = self._smart_api.generateToken(self._refresh_tkn)
            if resp.get("status"):
                self._auth_token = resp["data"]["jwtToken"]
                self._jwt_expiry = (
                    datetime.now(tz=timezone.utc)
                    + timedelta(hours=_JWT_TTL_HOURS)
                )
                logger.info("[angelone] JWT refreshed successfully.")
                return True
            # Refresh token expired — full re-login
            logger.warning("[angelone] Refresh token expired — re-logging in.")
            return self.login()
        except Exception as exc:
            logger.exception("[angelone] Token refresh error: %s", exc)
            return False

    def logout(self) -> bool:
        if self._smart_api:
            try:
                self._smart_api.terminateSession(self._client_id)
            except Exception:
                pass
        self._connected   = False
        self._auth_token  = ""
        self._jwt_expiry  = None
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Profile ───────────────────────────────────────────────────────────

    @_ensure_connected
    def get_profile(self) -> BrokerProfile:
        data = self._smart_api.getProfile(self._auth_token)["data"]
        return BrokerProfile(
            client_id = data.get("clientcode", ""),
            name      = data.get("name", ""),
            email     = data.get("email", ""),
            broker    = self.name,
            exchanges = data.get("exchanges", []),
            products  = data.get("products", []),
        )

    # ── Orders ────────────────────────────────────────────────────────────

    @_ensure_connected
    def place_order(self, order: BrokerOrder) -> str:
        """Place an order. order.token must be set (use angel_master.resolve_token)."""
        payload = {
            "variety":         order.variety,
            "tradingsymbol":   order.symbol,
            "symboltoken":     order.token,       # numeric string — REQUIRED
            "transactiontype": order.side.value,
            "exchange":        order.exchange.value,
            "ordertype":       order.order_type.value,
            "producttype":     order.product.value,
            "duration":        "DAY",
            "price":           str(order.price),
            "triggerprice":    str(order.trigger_price),
            "quantity":        str(order.quantity),
        }
        resp = self._smart_api.placeOrder(payload)
        return resp.get("data", {}).get("orderid", "")

    @_ensure_connected
    def cancel_order(self, order_id: str) -> bool:
        resp = self._smart_api.cancelOrder(order_id, "NORMAL")
        return bool(resp.get("status"))

    @_ensure_connected
    def get_order_status(self, order_id: str) -> dict[str, Any]:
        orders = self._smart_api.orderBook().get("data") or []
        for o in orders:
            if o.get("orderid") == order_id:
                return o
        return {}

    @_ensure_connected
    def get_orders(self) -> list[dict[str, Any]]:
        return self._smart_api.orderBook().get("data") or []

    # ── Positions ─────────────────────────────────────────────────────────

    @_ensure_connected
    def get_positions(self) -> list[BrokerPosition]:
        raw = self._smart_api.position().get("data") or []
        return [
            BrokerPosition(
                symbol    = p["tradingsymbol"],
                token     = p["symboltoken"],
                exchange  = p["exchange"],
                product   = p["producttype"],
                quantity  = int(p.get("netqty", 0)),
                avg_price = float(p.get("averageprice", 0)),
                ltp       = float(p.get("ltp", 0)),
                pnl       = float(p.get("unrealised", 0)),
            )
            for p in raw
        ]

    @_ensure_connected
    def get_holdings(self) -> list[dict[str, Any]]:
        return self._smart_api.holding().get("data") or []

    # ── Market data ───────────────────────────────────────────────────────

    @_ensure_connected
    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        resp = self._smart_api.ltpData(exchange, symbol, token)
        return float(resp.get("data", {}).get("ltp", 0.0))

    @_ensure_connected
    def get_candles(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        payload = {
            "exchange":    exchange,
            "symboltoken": symbol_token,
            "interval":    interval,
            "fromdate":    from_date,
            "todate":      to_date,
        }
        return self._smart_api.getCandleData(payload).get("data") or []

    # ── Funds ─────────────────────────────────────────────────────────────

    @_ensure_connected
    def get_funds(self) -> dict[str, Any]:
        return self._smart_api.rmsLimit().get("data") or {}
