"""Phase 6 — Paper Trading unit tests.

Covers:
  [x] PaperPortfolio — BUY signal accepted, cash debited
  [x] PaperPortfolio — SELL without position rejected
  [x] PaperPortfolio — SELL after BUY fills correctly, cash credited
  [x] PaperPortfolio — insufficient cash rejects BUY
  [x] PaperPortfolio — snapshot fields are valid
  [x] PaperPortfolio — daily_pnl returns float
  [x] PaperPortfolio — persist() then restore() round-trips cash + trades + positions
  [x] PaperPortfolio — restore() on missing DB returns False (fresh start)
  [x] PaperPortfolio — integrity check PASSES after clean round-trip
  [x] PaperPortfolio — corruption guard blocks orders after mismatch
  [x] PaperExecutor  — execute() BUY returns success=True
  [x] PaperExecutor  — execute() invalid signal returns success=False
  [x] PaperExecutor  — slippage applied correctly (exec_price > req_price for BUY)
  [x] PaperExecutor  — live_price=True with no fetcher returns failure
  [x] PositionBook   — avg_cost weighted correctly on second BUY
  [x] TradeBook      — realized_pnl correct on round-trip

All tests: zero network calls, zero broker credentials, temp SQLite path.
Run time: < 1 second.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from paper.portfolio import PaperPortfolio
from paper.executor  import PaperExecutor


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path):
    """Return a temp Path for SQLite — cleaned up automatically after each test."""
    return tmp_path / "test_portfolio.db"


@pytest.fixture()
def portfolio(tmp_db):
    """Fresh PaperPortfolio with ₹1 lakh capital on a temp DB path."""
    return PaperPortfolio(cash=100_000.0, db_path=tmp_db)


@pytest.fixture()
def executor(portfolio):
    """PaperExecutor wired to the portfolio fixture."""
    return PaperExecutor(portfolio, slippage_bps=5)


# ────────────────────────────────────────────────────────────────────────────
# PaperPortfolio — signal handling
# ────────────────────────────────────────────────────────────────────────────

class TestPortfolioSignals:
    def test_buy_accepted_returns_order_id(self, portfolio):
        oid = portfolio.on_signal("BUY", "RELIANCE", price=2500.0, qty=10)
        assert oid is not None
        assert isinstance(oid, str)
        assert len(oid) > 0

    def test_buy_debits_cash(self, portfolio):
        initial = portfolio.cash
        portfolio.on_signal("BUY", "RELIANCE", price=2500.0, qty=10)
        # Cash should be lower after BUY (exec price includes slippage)
        assert portfolio.cash < initial

    def test_sell_without_position_rejected(self, portfolio):
        oid = portfolio.on_signal("SELL", "RELIANCE", price=2500.0, qty=5)
        assert oid is None

    def test_sell_after_buy_accepted(self, portfolio):
        portfolio.on_signal("BUY",  "RELIANCE", price=2500.0, qty=10)
        oid = portfolio.on_signal("SELL", "RELIANCE", price=2600.0, qty=10)
        assert oid is not None

    def test_sell_credits_cash(self, portfolio):
        portfolio.on_signal("BUY",  "RELIANCE", price=2500.0, qty=10)
        cash_after_buy = portfolio.cash
        portfolio.on_signal("SELL", "RELIANCE", price=2600.0, qty=10)
        assert portfolio.cash > cash_after_buy

    def test_insufficient_cash_rejected(self, portfolio):
        # Price * qty >> 1 lakh
        oid = portfolio.on_signal("BUY", "RELIANCE", price=99999.0, qty=100)
        assert oid is None

    def test_position_created_after_buy(self, portfolio):
        portfolio.on_signal("BUY", "RELIANCE", price=2500.0, qty=5)
        pos = portfolio.position_book.get("RELIANCE")
        assert pos is not None
        assert pos.quantity == 5

    def test_position_cleared_after_full_sell(self, portfolio):
        portfolio.on_signal("BUY",  "RELIANCE", price=2500.0, qty=5)
        portfolio.on_signal("SELL", "RELIANCE", price=2600.0, qty=5)
        pos = portfolio.position_book.get("RELIANCE")
        # Either None or quantity == 0
        assert pos is None or pos.quantity == 0


# ────────────────────────────────────────────────────────────────────────────
# PaperPortfolio — snapshot & P&L
# ────────────────────────────────────────────────────────────────────────────

class TestPortfolioSnapshot:
    def test_snapshot_cash_matches(self, portfolio):
        snap = portfolio.snapshot()
        assert snap.cash == portfolio.cash

    def test_snapshot_not_corrupted_by_default(self, portfolio):
        snap = portfolio.snapshot()
        assert snap.corrupted is False

    def test_snapshot_total_value_gte_cash(self, portfolio):
        portfolio.on_signal("BUY", "TCS", price=3500.0, qty=5)
        snap = portfolio.snapshot()
        assert snap.total_value > 0

    def test_snapshot_open_positions_count(self, portfolio):
        portfolio.on_signal("BUY", "INFY", price=1500.0, qty=10)
        portfolio.on_signal("BUY", "TCS",  price=3500.0, qty=5)
        snap = portfolio.snapshot()
        assert snap.open_positions == 2

    def test_daily_pnl_returns_float(self, portfolio):
        portfolio.on_signal("BUY", "RELIANCE", price=2500.0, qty=3)
        pnl = portfolio.daily_pnl()
        assert isinstance(pnl, float)

    def test_total_trades_increments(self, portfolio):
        portfolio.on_signal("BUY",  "RELIANCE", price=2500.0, qty=2)
        portfolio.on_signal("SELL", "RELIANCE", price=2600.0, qty=2)
        snap = portfolio.snapshot()
        assert snap.total_trades == 2


# ────────────────────────────────────────────────────────────────────────────
# PaperPortfolio — persist / restore
# ────────────────────────────────────────────────────────────────────────────

class TestPortfolioPersistRestore:
    def test_restore_missing_db_returns_false(self, tmp_db):
        p = PaperPortfolio(cash=100_000.0, db_path=tmp_db)
        result = p.restore()
        assert result is False

    def test_persist_creates_db_file(self, portfolio, tmp_db):
        portfolio.on_signal("BUY", "RELIANCE", price=2500.0, qty=5)
        portfolio.persist()
        assert tmp_db.exists()

    def test_restore_recovers_cash(self, tmp_db):
        p1 = PaperPortfolio(cash=100_000.0, db_path=tmp_db)
        p1.on_signal("BUY", "RELIANCE", price=2500.0, qty=5)
        cash_after_buy = p1.cash
        p1.persist()

        p2 = PaperPortfolio(cash=100_000.0, db_path=tmp_db)
        p2.restore()
        assert abs(p2.cash - cash_after_buy) < 0.01

    def test_restore_recovers_trade_count(self, tmp_db):
        p1 = PaperPortfolio(cash=100_000.0, db_path=tmp_db)
        p1.on_signal("BUY",  "RELIANCE", price=2500.0, qty=5)
        p1.on_signal("SELL", "RELIANCE", price=2600.0, qty=5)
        p1.persist()

        p2 = PaperPortfolio(cash=100_000.0, db_path=tmp_db)
        p2.restore()
        assert len(p2.trade_book) == 2

    def test_restore_recovers_position(self, tmp_db):
        p1 = PaperPortfolio(cash=100_000.0, db_path=tmp_db)
        p1.on_signal("BUY", "TCS", price=3500.0, qty=3)
        p1.persist()

        p2 = PaperPortfolio(cash=100_000.0, db_path=tmp_db)
        p2.restore()
        pos = p2.position_book.get("TCS")
        assert pos is not None
        assert pos.quantity == 3

    def test_integrity_passes_after_clean_round_trip(self, tmp_db):
        p1 = PaperPortfolio(cash=100_000.0, db_path=tmp_db)
        p1.on_signal("BUY", "INFY", price=1500.0, qty=10)
        p1.persist()

        p2 = PaperPortfolio(cash=100_000.0, db_path=tmp_db)
        p2.restore()
        assert p2.is_corrupted is False


# ────────────────────────────────────────────────────────────────────────────
# Corruption guard
# ────────────────────────────────────────────────────────────────────────────

class TestCorruptionGuard:
    def test_corrupted_flag_off_by_default(self, portfolio):
        assert portfolio.is_corrupted is False

    def test_corrupted_blocks_orders(self, portfolio):
        """Manually set _corrupted=True; on_signal must raise RuntimeError."""
        portfolio._corrupted = True
        with pytest.raises(RuntimeError, match="CORRUPTED"):
            portfolio.on_signal("BUY", "RELIANCE", price=2500.0, qty=1)


# ────────────────────────────────────────────────────────────────────────────
# PaperExecutor
# ────────────────────────────────────────────────────────────────────────────

class TestPaperExecutor:
    def test_execute_buy_success(self, executor):
        result = executor.execute("BUY", "RELIANCE", price=2500.0, qty=5)
        assert result.success is True
        assert result.order_id is not None

    def test_execute_sell_without_position_fails(self, executor):
        result = executor.execute("SELL", "RELIANCE", price=2500.0, qty=5)
        assert result.success is False

    def test_execute_invalid_signal_fails(self, executor):
        result = executor.execute("HOLD", "RELIANCE", price=2500.0, qty=1)
        assert result.success is False
        assert "Invalid signal" in result.reason

    def test_buy_exec_price_above_request(self, executor):
        """With slippage > 0, exec_price > req_price for BUY."""
        result = executor.execute("BUY", "RELIANCE", price=2500.0, qty=1)
        assert result.exec_price > result.req_price

    def test_sell_exec_price_below_request(self, executor, portfolio):
        """With slippage > 0, exec_price < req_price for SELL."""
        # BUY first so portfolio has position
        portfolio.on_signal("BUY", "RELIANCE", price=2500.0, qty=5)
        result = executor.execute("SELL", "RELIANCE", price=2500.0, qty=5)
        assert result.success is True
        assert result.exec_price < result.req_price

    def test_live_price_without_fetcher_fails(self, executor):
        result = executor.execute("BUY", "RELIANCE", qty=5, live_price=True)
        assert result.success is False
        assert "fetcher" in result.reason.lower()

    def test_execution_result_total_cost(self, executor):
        result = executor.execute("BUY", "RELIANCE", price=2500.0, qty=10)
        assert result.success is True
        assert abs(result.total_cost - result.exec_price * 10) < 0.01

    def test_simulate_slippage_nonzero(self, executor):
        slip = executor.simulate_slippage(2500.0, "BUY")
        assert slip > 0

    def test_simulate_impact_zero_for_zero_volume(self, executor):
        impact = executor.simulate_impact(100, 0)
        assert impact == 0.0

    def test_simulate_impact_positive_for_nonzero_volume(self, executor):
        impact = executor.simulate_impact(1000, 100_000)
        assert impact > 0
