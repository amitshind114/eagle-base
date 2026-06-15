# -*- coding: utf-8 -*-
"""Phase 10d -- core.config.Settings unit tests.

Covers:
  Settings (core/config.py, pydantic-settings)

  Defaults
  [x] app_name == 'Eagle-Base'
  [x] app_version starts with a digit (semver)
  [x] debug == False by default
  [x] default_exchange == 'NSE'
  [x] default_interval == '1d'
  [x] default_period == '1y'
  [x] default_capital == 500_000.0
  [x] max_risk_per_trade_pct == 1.0
  [x] max_position_exposure_pct == 20.0
  [x] max_daily_loss == 10_000.0
  [x] max_open_positions == 5
  [x] max_drawdown_pct == 15.0
  [x] paper_capital == 500_000.0
  [x] paper_brokerage_pct == 0.03
  [x] angel credentials default to empty string

  Types
  [x] default_capital is float
  [x] max_open_positions is int
  [x] debug is bool
  [x] paper_brokerage_pct is float

  Env-var overrides
  [x] debug overridden by env var DEBUG=true
  [x] default_capital overridden by env var DEFAULT_CAPITAL=999999
  [x] max_open_positions overridden by env var MAX_OPEN_POSITIONS=10

  Module-level singleton
  [x] settings is a Settings instance
  [x] settings.app_name == 'Eagle-Base'

All tests: zero network, uses monkeypatch for env-var override tests.
"""

from __future__ import annotations

import os

import pytest

from core.config import Settings, settings


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestSettingsDefaults:
    @pytest.fixture()
    def s(self):
        """Fresh Settings() with no env file (env_file='': ignore missing)."""
        return Settings()

    def test_app_name(self, s):
        assert s.app_name == "Eagle-Base"

    def test_app_version_is_semver_like(self, s):
        assert s.app_version[0].isdigit()

    def test_debug_false_by_default(self, s):
        assert s.debug is False

    def test_default_exchange(self, s):
        assert s.default_exchange == "NSE"

    def test_default_interval(self, s):
        assert s.default_interval == "1d"

    def test_default_period(self, s):
        assert s.default_period == "1y"

    def test_default_capital(self, s):
        assert s.default_capital == 500_000.0

    def test_max_risk_per_trade(self, s):
        assert s.max_risk_per_trade_pct == 1.0

    def test_max_position_exposure(self, s):
        assert s.max_position_exposure_pct == 20.0

    def test_max_daily_loss(self, s):
        assert s.max_daily_loss == 10_000.0

    def test_max_open_positions(self, s):
        assert s.max_open_positions == 5

    def test_max_drawdown_pct(self, s):
        assert s.max_drawdown_pct == 15.0

    def test_paper_capital(self, s):
        assert s.paper_capital == 500_000.0

    def test_paper_brokerage_pct(self, s):
        assert s.paper_brokerage_pct == 0.03

    def test_angel_credentials_empty(self, s):
        assert s.angel_api_key == ""
        assert s.angel_client_id == ""
        assert s.angel_password == ""
        assert s.angel_totp_secret == ""


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class TestSettingsTypes:
    def test_default_capital_is_float(self):
        assert isinstance(Settings().default_capital, float)

    def test_max_open_positions_is_int(self):
        assert isinstance(Settings().max_open_positions, int)

    def test_debug_is_bool(self):
        assert isinstance(Settings().debug, bool)

    def test_paper_brokerage_is_float(self):
        assert isinstance(Settings().paper_brokerage_pct, float)


# ---------------------------------------------------------------------------
# Env-var overrides (monkeypatch -- never touches real .env)
# ---------------------------------------------------------------------------

class TestSettingsEnvOverride:
    def test_debug_env_override(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "true")
        s = Settings()
        assert s.debug is True

    def test_default_capital_env_override(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_CAPITAL", "999999")
        s = Settings()
        assert s.default_capital == 999_999.0

    def test_max_open_positions_env_override(self, monkeypatch):
        monkeypatch.setenv("MAX_OPEN_POSITIONS", "10")
        s = Settings()
        assert s.max_open_positions == 10


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

class TestSettingsSingleton:
    def test_singleton_is_settings_instance(self):
        assert isinstance(settings, Settings)

    def test_singleton_app_name(self):
        assert settings.app_name == "Eagle-Base"
