"""Angel One SmartAPI broker adapter.

Requires env vars:
    ANGELONE_API_KEY, ANGELONE_CLIENT_ID, ANGELONE_PASSWORD, ANGELONE_TOTP_SECRET

Dependency: pip install smartapi-python
"""

from __future__ import annotations

import os
from typing import Any

from brokers.base import BrokerBase
from brokers.models import BrokerOrder, BrokerPosition, BrokerProfile
from core.logger import get_logger

logger = get_logger(__name__)


class AngelOneBroker(BrokerBase):
    name = "angelone"

    def __init__(self) -> None:
        self._api_key = os.getenv("ANGELONE_API_KEY", "")
        self._client_id = os.getenv("ANGELONE_CLIENT_ID", "")
        self._password = os.getenv("ANGELONE_PASSWORD", "")
        self._totp_secret = os.getenv("ANGELONE_TOTP_SECRET", "")
        self._smart_api: Any = None
        self._auth_token: str = ""
        self._connected: bool = False

    # ------------------------------------------------------------------ auth
    def login(self) -> bool:
        try:
            import pyotp
            from SmartApi import SmartConnect  # type: ignore[import]

            totp = pyotp.TOTP(self._totp_secret).now()
            self._smart_api = SmartConnect(api_key=self._api_key)
            data = self._smart_api.generateSession(
                self._client_id, self._password, totp
            )
            if data.get("status"):
                self._auth_token = data["data"]["jwtToken"]
                self._connected = True
                logger.info("AngelOne login successful for %s", self._client_id)
                return True
            logger.error("AngelOne login failed: %s", data.get("message"))
            return False
        except Exception as exc:
            logger.exception("AngelOne login error: %s", exc)
            return False

    def logout(self) -> bool:
        if self._smart_api:
            self._smart_api.terminateSession(self._client_id)
        self._connected = False
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------ profile
    def get_profile(self) -> BrokerProfile:
        data = self._smart_api.getProfile(self._auth_token)["data"]
        return BrokerProfile(
            client_id=data.get("clientcode", ""),
            name=data.get("name", ""),
            email=data.get("email", ""),
            broker=self.name,
            exchanges=data.get("exchanges", []),
            products=data.get("products", []),
        )

    # ------------------------------------------------------------------ orders
    def place_order(self, order: BrokerOrder) -> str:
        payload = {
            "variety": order.variety,
            "tradingsymbol": order.symbol,
            "symboltoken": order.token,
            "transactiontype": order.side.value,
            "exchange": order.exchange.value,
            "ordertype": order.order_type.value,
            "producttype": order.product.value,
            "duration": "DAY",
            "price": str(order.price),
            "triggerprice": str(order.trigger_price),
            "quantity": str(order.quantity),
        }
        resp = self._smart_api.placeOrder(payload)
        return resp.get("data", {}).get("orderid", "")

    def cancel_order(self, order_id: str) -> bool:
        resp = self._smart_api.cancelOrder(order_id, "NORMAL")
        return bool(resp.get("status"))

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        orders = self._smart_api.orderBook().get("data") or []
        for o in orders:
            if o.get("orderid") == order_id:
                return o
        return {}

    def get_orders(self) -> list[dict[str, Any]]:
        return self._smart_api.orderBook().get("data") or []

    # ------------------------------------------------------------------ positions
    def get_positions(self) -> list[BrokerPosition]:
        raw = self._smart_api.position().get("data") or []
        return [
            BrokerPosition(
                symbol=p["tradingsymbol"],
                token=p["symboltoken"],
                exchange=p["exchange"],
                product=p["producttype"],
                quantity=int(p.get("netqty", 0)),
                avg_price=float(p.get("averageprice", 0)),
                ltp=float(p.get("ltp", 0)),
                pnl=float(p.get("unrealised", 0)),
            )
            for p in raw
        ]

    def get_holdings(self) -> list[dict[str, Any]]:
        return self._smart_api.holding().get("data") or []

    # ------------------------------------------------------------------ market data
    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        resp = self._smart_api.ltpData(exchange, symbol, token)
        return float(resp.get("data", {}).get("ltp", 0.0))

    def get_candles(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        payload = {
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date,
        }
        return self._smart_api.getCandleData(payload).get("data") or []

    # ------------------------------------------------------------------ funds
    def get_funds(self) -> dict[str, Any]:
        return self._smart_api.rmsLimit().get("data") or {}
