"""Fyers API V3 broker adapter (stub).

Requires env vars:
    FYERS_APP_ID, FYERS_ACCESS_TOKEN

Dependency: pip install fyers-apiv3
"""

from __future__ import annotations

import os
from typing import Any

from brokers.base import BrokerBase
from brokers.models import BrokerOrder, BrokerPosition, BrokerProfile
from core.logger import get_logger

logger = get_logger(__name__)


class FyersBroker(BrokerBase):
    name = "fyers"

    def __init__(self) -> None:
        self._app_id = os.getenv("FYERS_APP_ID", "")
        self._access_token = os.getenv("FYERS_ACCESS_TOKEN", "")
        self._fyers: Any = None
        self._connected: bool = False

    def login(self) -> bool:
        try:
            from fyers_apiv3 import fyersModel  # type: ignore[import]

            self._fyers = fyersModel.FyersModel(
                client_id=self._app_id,
                token=self._access_token,
                log_path="",
            )
            self._connected = True
            logger.info("Fyers adapter connected")
            return True
        except Exception as exc:
            logger.exception("Fyers login error: %s", exc)
            return False

    def logout(self) -> bool:
        self._connected = False
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_profile(self) -> BrokerProfile:
        resp = self._fyers.get_profile()
        d = resp.get("data", {})
        return BrokerProfile(
            client_id=d.get("fy_id", ""),
            name=d.get("name", ""),
            email=d.get("email_id", ""),
            broker=self.name,
        )

    def place_order(self, order: BrokerOrder) -> str:
        payload = {
            "symbol": f"{order.exchange.value}:{order.symbol}-EQ",
            "qty": order.quantity,
            "type": {"MARKET": 2, "LIMIT": 1, "SL": 3, "SL-M": 4}.get(
                order.order_type.value, 2
            ),
            "side": 1 if order.side.value == "BUY" else -1,
            "productType": order.product.value,
            "limitPrice": order.price,
            "stopPrice": order.trigger_price,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        resp = self._fyers.place_order(payload)
        return resp.get("id", "")

    def cancel_order(self, order_id: str) -> bool:
        resp = self._fyers.cancel_order({"id": order_id})
        return resp.get("s") == "ok"

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        orders = self._fyers.orderbook().get("orderBook") or []
        for o in orders:
            if o.get("id") == order_id:
                return o
        return {}

    def get_orders(self) -> list[dict[str, Any]]:
        return self._fyers.orderbook().get("orderBook") or []

    def get_positions(self) -> list[BrokerPosition]:
        raw = self._fyers.positions().get("netPositions") or []
        return [
            BrokerPosition(
                symbol=p["symbol"],
                token=p.get("id", ""),
                exchange=p["symbol"].split(":")[0],
                product=p.get("productType", ""),
                quantity=int(p.get("netQty", 0)),
                avg_price=float(p.get("netAvg", 0)),
                ltp=float(p.get("ltp", 0)),
                pnl=float(p.get("pl", 0)),
            )
            for p in raw
        ]

    def get_holdings(self) -> list[dict[str, Any]]:
        return self._fyers.holdings().get("holdings") or []

    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        key = f"{exchange}:{symbol}-EQ"
        resp = self._fyers.quotes({"symbols": key})
        data = (resp.get("d") or [{}])[0]
        return float(data.get("v", {}).get("lp", 0.0))

    def get_candles(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        import datetime

        payload = {
            "symbol": f"{exchange}:{symbol_token}-EQ",
            "resolution": interval,
            "date_format": "1",
            "range_from": from_date,
            "range_to": to_date,
            "cont_flag": "1",
        }
        resp = self._fyers.history(payload)
        candles = resp.get("candles") or []
        keys = ["timestamp", "open", "high", "low", "close", "volume"]
        return [dict(zip(keys, c)) for c in candles]

    def get_funds(self) -> dict[str, Any]:
        return self._fyers.funds().get("fund_limit") or {}
