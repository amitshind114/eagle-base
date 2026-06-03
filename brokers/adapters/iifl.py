"""IIFL / 5paisa broker adapter (stub).

Requires env vars:
    IIFL_APP_NAME, IIFL_APP_SOURCE, IIFL_USER_ID, IIFL_PASSWORD,
    IIFL_USER_KEY, IIFL_ENCRYPTION_KEY

Dependency: pip install py5paisa
"""

from __future__ import annotations

import os
from typing import Any

from brokers.base import BrokerBase
from brokers.models import BrokerOrder, BrokerPosition, BrokerProfile
from core.logger import get_logger

logger = get_logger(__name__)


class IIFLBroker(BrokerBase):
    name = "iifl"

    def __init__(self) -> None:
        self._cred = {
            "APP_NAME": os.getenv("IIFL_APP_NAME", ""),
            "APP_SOURCE": os.getenv("IIFL_APP_SOURCE", ""),
            "USER_ID": os.getenv("IIFL_USER_ID", ""),
            "PASSWORD": os.getenv("IIFL_PASSWORD", ""),
            "USER_KEY": os.getenv("IIFL_USER_KEY", ""),
            "ENCRYPTION_KEY": os.getenv("IIFL_ENCRYPTION_KEY", ""),
        }
        self._client: Any = None
        self._connected: bool = False

    def login(self) -> bool:
        try:
            from py5paisa import FivePaisaClient  # type: ignore[import]

            self._client = FivePaisaClient(cred=self._cred)
            self._client.login(
                self._cred["USER_ID"], self._cred["PASSWORD"]
            )
            self._connected = True
            logger.info("IIFL/5paisa adapter connected")
            return True
        except Exception as exc:
            logger.exception("IIFL login error: %s", exc)
            return False

    def logout(self) -> bool:
        self._connected = False
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_profile(self) -> BrokerProfile:
        return BrokerProfile(
            client_id=self._cred["USER_ID"],
            name="",
            email="",
            broker=self.name,
        )

    def place_order(self, order: BrokerOrder) -> str:
        resp = self._client.place_order(
            OrderType="B" if order.side.value == "BUY" else "S",
            Exchange="N" if "NSE" in order.exchange.value else "B",
            ExchangeType="C",
            ScripCode=int(order.token),
            Qty=order.quantity,
            Price=order.price,
            IsIntraday=order.product.value == "INTRADAY",
        )
        return str(resp.get("BrokerOrderId", ""))

    def cancel_order(self, order_id: str) -> bool:
        return True  # implement with client.cancel_order

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        return {}

    def get_orders(self) -> list[dict[str, Any]]:
        return self._client.order_book() or []

    def get_positions(self) -> list[BrokerPosition]:
        raw = self._client.positions() or []
        return [
            BrokerPosition(
                symbol=p.get("Symbol", ""),
                token=str(p.get("ScripCode", "")),
                exchange=p.get("Exch", ""),
                product=p.get("ExchType", ""),
                quantity=int(p.get("NetQty", 0)),
                avg_price=float(p.get("AvgRate", 0)),
                ltp=float(p.get("LTP", 0)),
                pnl=float(p.get("MTOM", 0)),
            )
            for p in raw
        ]

    def get_holdings(self) -> list[dict[str, Any]]:
        return self._client.holdings() or []

    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        req = [{"Exch": exchange, "ExchType": "C", "ScripCode": int(token)}]
        resp = self._client.fetch_market_feed(req)
        data = (resp.get("Data") or [{}])[0]
        return float(data.get("LastRate", 0.0))

    def get_candles(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        import pandas as pd

        df = self._client.historical_data(
            Exch=exchange,
            ExchangeSegment="C",
            ScripCode=int(symbol_token),
            time=interval,
            From=from_date,
            To=to_date,
        )
        if isinstance(df, pd.DataFrame):
            return df.to_dict("records")
        return []

    def get_funds(self) -> dict[str, Any]:
        return self._client.margin() or {}
