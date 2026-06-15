"""Central application settings — loaded from .env via pydantic-settings.

Field names map 1-to-1 to environment variable names (upper-cased).
All broker credential fields match the keys in .env.example exactly
so that pydantic-settings resolves them without alias gymnastics.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── App ───────────────────────────────────────────────────────────────
    app_name:    str  = "Eagle-Base"
    app_version: str  = "0.1.0"
    debug:       bool = False
    log_level:   str  = "INFO"
    db_url:      str  = "sqlite:///eagle.db"
    broker:      str  = "angelone"

    # ── API authentication (X-API-Key for /api/live and /api/paper) ───────
    # Generate: python -c "import secrets; print(secrets.token_hex(32))"
    # Leave empty in .env to disable enforcement (local dev only).
    api_key: str = ""

    # ── Data defaults ─────────────────────────────────────────────────────
    default_exchange:  str = "NSE"
    default_interval:  str = "1d"
    default_period:    str = "1y"

    # ── Risk defaults ─────────────────────────────────────────────────────
    default_capital:           float = 500_000.0
    max_risk_per_trade_pct:    float = 1.0
    max_position_exposure_pct: float = 20.0
    max_daily_loss:            float = 10_000.0
    max_open_positions:        int   = 5
    max_drawdown_pct:          float = 15.0

    # ── Paper trading ─────────────────────────────────────────────────────
    paper_capital:       float = 500_000.0
    paper_brokerage_pct: float = 0.03

    # ── Angel One SmartAPI ────────────────────────────────────────────────
    # Field names match .env.example keys exactly (ANGELONE_* prefix).
    # Previously named angel_* which mapped to ANGEL_* — one character
    # short — causing all credentials to silently default to "".
    angelone_api_key:    str = ""
    angelone_client_id:  str = ""
    angelone_password:   str = ""
    angelone_totp_secret: str = ""

    # ── Zerodha Kite Connect ──────────────────────────────────────────────
    zerodha_api_key:      str = ""
    zerodha_api_secret:   str = ""
    zerodha_request_token: str = ""

    # ── Upstox V2 ─────────────────────────────────────────────────────────
    upstox_api_key:    str = ""
    upstox_api_secret: str = ""
    upstox_access_token: str = ""

    # ── Fyers API V3 ──────────────────────────────────────────────────────
    fyers_app_id:      str = ""
    fyers_access_token: str = ""

    # ── IIFL / 5paisa ─────────────────────────────────────────────────────
    iifl_app_name:      str = ""
    iifl_app_source:    str = ""
    iifl_user_id:       str = ""
    iifl_password:      str = ""
    iifl_user_key:      str = ""
    iifl_encryption_key: str = ""


settings = Settings()
