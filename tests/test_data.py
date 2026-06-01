"""Tests — Data Module (Priority 1)."""

from __future__ import annotations

import pandas as pd
import pytest

from data.fetcher import YFinanceProvider
from data.cache import DataCache
from data.manager import DataManager


class TestYFinanceProvider:
    def test_init(self):
        provider = YFinanceProvider()
        assert provider.name == "yfinance"

    def test_health_check_returns_dict(self):
        provider = YFinanceProvider()
        result = provider.health_check()
        assert isinstance(result, dict)
        assert "status" in result

    def test_fetch_ohlcv_returns_dataframe(self):
        """Live test — requires internet."""
        provider = YFinanceProvider()
        df = provider.fetch_ohlcv("AAPL", "1d", "2024-01-01", "2024-01-31")
        assert isinstance(df, pd.DataFrame)
        if not df.empty:
            assert "Close" in df.columns
            assert "Open" in df.columns

    def test_fetch_quote_returns_dict(self):
        provider = YFinanceProvider()
        quote = provider.fetch_quote("AAPL")
        assert isinstance(quote, dict)
        assert "symbol" in quote


class TestDataCache:
    def test_miss_returns_none(self, tmp_path, monkeypatch):
        import data.cache as cache_module
        monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path)
        cache = DataCache()
        result = cache.read("TEST", "1d", "2024-01-01", "2024-01-31")
        assert result is None

    def test_write_and_read(self, tmp_path, monkeypatch):
        import data.cache as cache_module
        monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path)
        cache = DataCache()
        df = pd.DataFrame({"Open": [100], "Close": [105]})
        cache.write(df, "TEST", "1d", "2024-01-01", "2024-01-31")
        result = cache.read("TEST", "1d", "2024-01-01", "2024-01-31")
        assert result is not None
        assert len(result) == 1


class TestDataManager:
    def test_init(self):
        manager = DataManager()
        assert manager.provider is not None
        assert manager.cache is not None

    def test_health_check(self):
        manager = DataManager()
        health = manager.health_check()
        assert "provider" in health
        assert "cache_files" in health
