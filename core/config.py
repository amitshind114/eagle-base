"""Central application settings loaded from .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "Eagle-Base"
    app_version: str = "0.1.0"
    debug: bool = False

    # Data
    default_exchange: str = "NSE"
    default_interval: str = "1d"
    default_period: str = "1y"

    # Risk defaults
    default_capital: float = 500_000.0
    max_risk_per_trade_pct: float = 1.0
    max_position_exposure_pct: float = 20.0
    max_daily_loss: float = 10_000.0
    max_open_positions: int = 5
    max_drawdown_pct: float = 15.0

    # Paper trading
    paper_capital: float = 500_000.0
    paper_brokerage_pct: float = 0.03

    # Angel One (optional — for live later)
    angel_api_key: str = ""
    angel_client_id: str = ""
    angel_password: str = ""
    angel_totp_secret: str = ""


settings = Settings()
