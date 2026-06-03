"""Upstox V2 broker adapter (stub — implement after OAuth flow).

Requires env vars:
    UPSTOX_API_KEY, UPSTOX_API_SECRET, UPSTOX_ACCESS_TOKEN

Dependency: pip install upstox-python-sdk
"""

from __future__ import annotations

import os
from typing import Any

from brokers.base import BrokerBase
from brokers.models import BrokerOrder, BrokerPosition, BrokerProfile
from core.logger import get_logger

logger = get_logger(__name__)


class UpstoxBroker(BrokerBase):
    name = "upstox"

    def __init__(self) -> None:
        self._access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
        self._connected: bool = False
        self._config: Any = None

    def login(self) -> bool:
        try:
            import upstox_client  # type: ignore[import]

            configuration = upstox_client.Configuration()
            configuration.access_token = self._access_token
            self._config = configuration
            self._connected = True
            logger.info("Upstox adapter connected via access token")
            return True
        except Exception as exc:
            logger.exception("Upstox login error: %s", exc)
            return False

    def logout(self) -> bool:
        self._connected = False
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_profile(self) -> BrokerProfile:
        import upstox_client  # type: ignore[import]

        api = upstox_client.UserApi(upstox_client.ApiClient(self._config))
        p = api.get_profile("2.0").data
        return BrokerProfile(
            client_id=p.user_id,
            name=p.user_name,
            email=p.email,
            broker=self.name,
        )

    def place_order(self, order: BrokerOrder) -> str:
        import upstox_client  # type: ignore[import]

        api = upstox_client.OrderApi(upstox_client.ApiClient(self._config))
        body = upstox_client.PlaceOrderRequest(
            quantity=order.quantity,
            product=order.product.value,
            validity="DAY",
            price=order.price,
            tag=order.tag,
            instrument_token=f"{order.exchange.value}_EQ|{order.token}",
            order_type=order.order_type.value,
            transaction_type=order.side.value,
            disclosed_quantity=0,
            trigger_price=order.trigger_price,
            is_amo=False,
        )
        resp = api.place_order(body, "2.0")
        return resp.data.order_id

    def cancel_order(self, order_id: str) -> bool:
        import upstox_client  # type: ignore[import]

        api = upstox_client.OrderApi(upstox_client.ApiClient(self._config))
        api.cancel_order(order_id, "2.0")
        return True

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        import upstox_client  # type: ignore[import]

        api = upstox_client.OrderApi(upstox_client.ApiClient(self._config))
        resp = api.get_order_details("2.0", order_id=order_id)
        return vars(resp.data) if resp.data else {}

    def get_orders(self) -> list[dict[str, Any]]:
        import upstox_client  # type: ignore[import]

        api = upstox_client.OrderApi(upstox_client.ApiClient(self._config))
        resp = api.get_order_book("2.0")
        return [vars(o) for o in (resp.data or [])]

    def get_positions(self) -> list[BrokerPosition]:
        import upstox_client  # type: ignore[import]

        api = upstox_client.PortfolioApi(upstox_client.ApiClient(self._config))
        resp = api.get_positions("2.0")
        return [
            BrokerPosition(
                symbol=p.trading_symbol,
                token=p.instrument_token,
                exchange=p.exchange,
                product=p.product,
                quantity=p.quantity,
                avg_price=p.average_price or 0.0,
                ltp=p.last_price or 0.0,
                pnl=p.pnl or 0.0,
            )
            for p in (resp.data or [])
        ]

    def get_holdings(self) -> list[dict[str, Any]]:
        import upstox_client  # type: ignore[import]

        api = upstox_client.PortfolioApi(upstox_client.ApiClient(self._config))
        resp = api.get_holdings("2.0")
        return [vars(h) for h in (resp.data or [])]

    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        import upstox_client  # type: ignore[import]

        api = upstox_client.MarketQuoteApi(upstox_client.ApiClient(self._config))
        key = f"{exchange}_EQ|{token}"
        resp = api.ltp(key, "2.0")
        data = resp.data or {}
        entry = data.get(key, {})
        return float(getattr(entry, "last_price", 0.0))

    def get_candles(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        import upstox_client  # type: ignore[import]

        api = upstox_client.HistoryApi(upstox_client.ApiClient(self._config))
        instrument = f"{exchange}_EQ|{symbol_token}"
        resp = api.get_historical_candle_data1(
            instrument, interval, to_date, from_date, "2.0"
        )
        return [vars(c) for c in (resp.data.candles if resp.data else [])]

    def get_funds(self) -> dict[str, Any]:
        import upstox_client  # type: ignore[import]

        api = upstox_client.UserApi(upstox_client.ApiClient(self._config))
        resp = api.get_user_fund_margin("2.0")
        return vars(resp.data) if resp.data else {}
