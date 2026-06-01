"""Core module tests."""

from __future__ import annotations


def test_settings_loads():
    """Settings should load without errors."""
    from core.config import settings
    assert settings is not None


def test_logger_exists():
    """Logger should be importable."""
    from core.logger import logger
    assert logger is not None
