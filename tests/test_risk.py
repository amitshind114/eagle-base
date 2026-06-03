"""Tests for risk manager."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from risk.manager import RiskManager


class TestRiskManager:
    def test_position_size_basic(self):
        rm = RiskManager(capital=500_000)
        result = rm.position_size("RELIANCE.NS", entry_price=2500, stop_loss_points=50, risk_pct=1.0)
        assert result.quantity == 100
        assert result.risk_amount == 5000.0

    def test_position_size_exposure_warning(self):
        rm = RiskManager(capital=100_000)
        result = rm.position_size("TCS.NS", entry_price=4000, stop_loss_points=10, risk_pct=1.0)
        # qty = 100, exposure = 400,000 = 400% — should trigger warning
        assert len(result.warnings) > 0
        assert not result.is_within_limits

    def test_check_limits_no_breach(self):
        rm = RiskManager()
        breaches = rm.check_limits(daily_pnl=-1000, open_positions=3, current_drawdown_pct=-5, margin_used_pct=30)
        assert breaches == []

    def test_check_limits_breach(self):
        rm = RiskManager()
        breaches = rm.check_limits(daily_pnl=-15000, open_positions=3, current_drawdown_pct=-5, margin_used_pct=30)
        assert len(breaches) > 0
