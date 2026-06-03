"""Zerodha Kite Connect broker adapter.

Requires env vars:
    ZERODHA_API_KEY, ZERODHA_API_SECRET, ZERODHA_REQUEST_TOKEN

Dependency: pip install kiteconnect
"""

from __future__ import annotations

import os
from typing import Any

from brokers.base import BrokerBase
from brokers.models import BrokerOrder, BrokerPosition, BrokerProfile
from core.logger import get_logger

logger = get_logger(__name__)


class ZerodhaBroker(BrokerBase):
    name = "zerodha"

    def __init__(self) -> None:
        self._api_key = os.getenv("ZERODHA_API_KEY", "")
        self._api_secret = os.getenv("ZERODHA_API_SECRET", "")
        self._request_token = os.getenv("ZERODHA_REQUEST_TOKEN", "")
        self._kite: Any = None
        self._connected: bool = False

    def login(self) -> bool:
        try:
            from kiteconnect import KiteConnect  # type: ignore[import]

            self._kite = KiteConnect(api_key=self._api_key)
            data = self._kite.generate_session(
                self._request_token, api_secret=self._api_secret
            )
            self._kite.set_access_token(data["access_token"])
            self._connected = True
            logger.info("Zerodha login successful")
            return True
        except Exception as exc:
            logger.exception("Zerodha login error: %s", exc)
            return False

    def logout(self) -> bool:
        if self._kite:
            self._kite.invalidate_access_token()
        self._connected = False
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_profile(self) -> BrokerProfile:
        p = self._kite.profile()
        return BrokerProfile(
            client_id=p.get("user_id", ""),
            name=p.get("user_name", ""),
            email=p.get("email", ""),
            broker=self.name,
            exchanges=p.get("exchanges", []),
            products=p.get("products", []),
        )

    def place_order(self, order: BrokerOrder) -> str:
        from kiteconnect import KiteConnect  # type: ignore[import]

        order_id = self._kite.place_order(
            variety=KiteConnect.VARIETY_REGULAR,
            exchange=order.exchange.value,
            tradingsymbol=order.symbol,
            transaction_type=order.side.value,
            quantity=order.quantity,
            product=order.product.value,
            order_type=order.order_type.value,
            price=order.price or None,
            trigger_price=order.trigger_price or None,
            tag=order.tag,
        )
        return str(order_id)

    def cancel_order(self, order_id: str) -> bool:
        from kiteconnect import KiteConnect  # type: ignore[import]

        self._kite.cancel_order(
            variety=KiteConnect.VARIETY_REGULAR, order_id=order_id
        )
        return True

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        orders = self._kite.orders()
        for o in orders:
            if str(o.get("order_id")) == order_id:
                return o
        return {}

    def get_orders(self) -> list[dict[str, Any]]:
        return self._kite.orders()

    def get_positions(self) -> list[BrokerPosition]:
        raw = self._kite.positions().get("net", [])
        return [
            BrokerPosition(
                symbol=p["tradingsymbol"],
                token=str(p.get("instrument_token", "")),
                exchange=p["exchange"],
                product=p["product"],
                quantity=int(p.get("quantity", 0)),
                avg_price=float(p.get("average_price", 0)),
                ltp=float(p.get("last_price", 0)),
                pnl=float(p.get("unrealised", 0)),
            )
            for p in raw
        ]

    def get_holdings(self) -> list[dict[str, Any]]:
        return self._kite.holdings()

    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        key = f"{exchange}:{symbol}"
        resp = self._kite.ltp([key])
        return float(resp.get(key, {}).get("last_price", 0.0))

    def get_candles(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        import datetime

        records = self._kite.historical_data(
            instrument_token=int(symbol_token),
            from_date=datetime.datetime.fromisoformat(from_date),
            to_date=datetime.datetime.fromisoformat(to_date),
            interval=interval,
        )
        return records

    def get_funds(self) -> dict[str, Any]:
        return self._kite.margins() or {}
