"""Angel One SmartAPI provider — Phase 3 (stub).

Fill in credentials and API calls when Angel One access is available.
Until then, DataManager automatically falls back to YahooProvider.

To activate:
    1. pip install smartapi-python
    2. Set env vars: ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP
    3. Implement fetch() using SmartAPI historical data endpoint
    4. Set is_available() to check env vars + login success
"""

from __future__ import annotations

from datetime import datetime
from typing import List

import os
import pandas as pd

from core.logger import get_logger
from .base import DataProvider

log = get_logger("data.providers.angel")

_SUPPORTED_INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "1d"]

_REQUIRED_ENV = [
    "ANGEL_API_KEY",
    "ANGEL_CLIENT_ID",
    "ANGEL_PASSWORD",
    "ANGEL_TOTP",
]


class AngelProvider(DataProvider):
    """Angel One SmartAPI data provider — STUB.

    Returns empty DataFrames until credentials are configured.
    DataManager will skip this and use the next available provider.
    """

    def name(self) -> str:
        return "Angel One SmartAPI"

    def is_available(self) -> bool:
        """Return True only when all required env vars are set."""
        missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
        if missing:
            log.debug(f"[Angel] Not available — missing env vars: {missing}")
            return False
        # TODO: attempt SmartAPI login and return True on success
        return False

    def supported_intervals(self) -> List[str]:
        return _SUPPORTED_INTERVALS

    def fetch(
        self,
        symbol: str,
        from_dt: datetime,
        to_dt: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """NOT IMPLEMENTED — returns empty DataFrame.

        Replace this body with SmartAPI historical data call.
        See Angel One SmartAPI docs: https://smartapi.angelbroking.com/docs
        """
        log.warning(
            f"[Angel] fetch() called but provider is a stub. "
            f"Implement SmartAPI integration to activate."
        )
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    def fetch_latest_price(self, symbol: str) -> float:
        """NOT IMPLEMENTED — returns 0.0 (DataManager will fall back)."""
        return 0.0

    # ── TODO: implement when Angel One credentials are available ────────
    # def _login(self) -> SmartConnect:
    #     from SmartApi import SmartConnect
    #     import pyotp
    #     obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    #     totp = pyotp.TOTP(os.getenv("ANGEL_TOTP")).now()
    #     obj.generateSession(
    #         os.getenv("ANGEL_CLIENT_ID"),
    #         os.getenv("ANGEL_PASSWORD"),
    #         totp
    #     )
    #     return obj
