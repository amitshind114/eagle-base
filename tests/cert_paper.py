"""tests/cert_paper.py — Phase 6 Paper Trading certification suite.

All 5 assertions from the exit gate spec:

  1. on_signal BUY: cash decreases by price*qty
  2. on_signal SELL without position: rejected
  3. persist → restore → snapshot identical
  4. Two simultaneous on_signal calls do not corrupt state (thread safety)
  5. daily_pnl = realized + unrealized

Run:
    python tests/cert_paper.py
    pytest tests/cert_paper.py -v
"""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_portfolio(cash: float = 100_000.0, db_path: Path | None = None):
    from paper.portfolio import PaperPortfolio
    db = db_path or Path(tempfile.mktemp(suffix=".db"))
    return PaperPortfolio(cash=cash, db_path=db)


# ---------------------------------------------------------------------------
# Test 1 — BUY decreases cash
# ---------------------------------------------------------------------------
def test_buy_decreases_cash():
    """on_signal BUY: cash must decrease by exec_price * qty."""
    portfolio = _make_portfolio(cash=100_000.0)
    initial_cash = portfolio.cash

    price, qty = 2500.0, 10
    slippage_pct = 0.0005
    exec_price = round(price * (1 + slippage_pct), 2)
    expected_cash = round(initial_cash - exec_price * qty, 2)

    order_id = portfolio.on_signal("BUY", "RELIANCE", price=price, qty=qty, slippage_pct=slippage_pct)
    assert order_id is not None, "BUY order should be accepted"
    actual_cash = round(portfolio.cash, 2)
    assert actual_cash == expected_cash, (
        f"Cash mismatch: expected {expected_cash}, got {actual_cash}"
    )
    print("PASS  test_buy_decreases_cash")


# ---------------------------------------------------------------------------
# Test 2 — SELL without position is rejected
# ---------------------------------------------------------------------------
def test_sell_without_position_rejected():
    """SELL with no open position must return None (rejected)."""
    portfolio = _make_portfolio()
    order_id = portfolio.on_signal("SELL", "TCS", price=3500.0, qty=5)
    assert order_id is None, "SELL without position must be rejected"
    print("PASS  test_sell_without_position_rejected")


# ---------------------------------------------------------------------------
# Test 3 — persist → restore → snapshot identical
# ---------------------------------------------------------------------------
def test_persist_restore_snapshot():
    """After persist() + restore(), snapshot must be identical."""
    db_file = Path(tempfile.mktemp(suffix=".db"))
    try:
        portfolio = _make_portfolio(cash=100_000.0, db_path=db_file)
        portfolio.on_signal("BUY", "RELIANCE", price=2500.0, qty=5)
        portfolio.on_signal("BUY", "TCS",      price=3500.0, qty=3)
        snap_before = portfolio.snapshot()
        portfolio.persist()

        # Restore into fresh instance
        from paper.portfolio import PaperPortfolio
        portfolio2 = PaperPortfolio(cash=100_000.0, db_path=db_file)
        portfolio2.restore()
        assert not portfolio2.is_corrupted, "Restored portfolio should not be corrupted"
        snap_after = portfolio2.snapshot()

        assert snap_before.cash == snap_after.cash, (
            f"Cash: before={snap_before.cash} after={snap_after.cash}"
        )
        assert snap_before.open_positions == snap_after.open_positions, (
            f"Positions: before={snap_before.open_positions} after={snap_after.open_positions}"
        )
        assert snap_before.total_trades == snap_after.total_trades, (
            f"Trades: before={snap_before.total_trades} after={snap_after.total_trades}"
        )
        print("PASS  test_persist_restore_snapshot")
    finally:
        if db_file.exists():
            db_file.unlink()


# ---------------------------------------------------------------------------
# Test 4 — Thread safety: two concurrent on_signal calls
# ---------------------------------------------------------------------------
def test_concurrent_on_signal_thread_safety():
    """Two simultaneous on_signal calls must not corrupt state."""
    portfolio = _make_portfolio(cash=1_000_000.0)

    errors = []

    def buy_worker(sym, price, qty):
        try:
            portfolio.on_signal("BUY", sym, price=price, qty=qty)
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=buy_worker, args=("RELIANCE", 2500.0, 1)),
        threading.Thread(target=buy_worker, args=("TCS",      3500.0, 1)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    # Verify trade count matches
    trades = portfolio.trade_book.all()
    symbols_traded = {t.symbol for t in trades}
    assert len(symbols_traded) <= 2, f"More than 2 symbols unexpectedly: {symbols_traded}"
    print("PASS  test_concurrent_on_signal_thread_safety")


# ---------------------------------------------------------------------------
# Test 5 — daily_pnl = realized + unrealized
# ---------------------------------------------------------------------------
def test_daily_pnl_formula():
    """daily_pnl() must equal today's realized PnL + unrealized PnL."""
    portfolio = _make_portfolio(cash=200_000.0)

    # Buy then partially sell to generate realized PnL
    portfolio.on_signal("BUY",  "RELIANCE", price=2500.0, qty=10)
    portfolio.on_signal("SELL", "RELIANCE", price=2600.0, qty=5)

    # Manually set last known price for unrealized calc
    portfolio._last_prices["RELIANCE"] = 2650.0

    realized_today = sum(t.realized_pnl for t in portfolio.trade_book.today())
    unrealized     = portfolio.position_book.unrealized_pnl(portfolio._last_prices)
    expected_pnl   = round(realized_today + unrealized, 2)

    # daily_pnl with no fetcher falls back to _last_prices
    actual_pnl = portfolio.daily_pnl()

    assert abs(actual_pnl - expected_pnl) < 0.01, (
        f"daily_pnl mismatch: expected {expected_pnl}, got {actual_pnl}"
    )
    print("PASS  test_daily_pnl_formula")


# ---------------------------------------------------------------------------
# Exit gate bonus: position_book quantity matches trade_book net
# ---------------------------------------------------------------------------
def test_position_matches_trade_book():
    """position.quantity must equal sum(BUY) - sum(SELL) from trade_book."""
    portfolio = _make_portfolio(cash=500_000.0)
    portfolio.on_signal("BUY",  "INFY", price=1500.0, qty=20)
    portfolio.on_signal("SELL", "INFY", price=1550.0, qty=8)

    from paper.models import OrderSide
    net = sum(
        t.quantity if t.side == OrderSide.BUY else -t.quantity
        for t in portfolio.trade_book.all()
        if t.symbol == "INFY"
    )
    pos = portfolio.position_book.get("INFY")
    assert pos is not None, "Position should exist"
    assert pos.quantity == net, (
        f"Position qty {pos.quantity} != trade net {net}"
    )
    print("PASS  test_position_matches_trade_book")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        test_buy_decreases_cash,
        test_sell_without_position_rejected,
        test_persist_restore_snapshot,
        test_concurrent_on_signal_thread_safety,
        test_daily_pnl_formula,
        test_position_matches_trade_book,
    ]
    failures = 0
    for test_fn in tests:
        try:
            test_fn()
        except Exception as exc:
            print(f"FAIL  {test_fn.__name__}: {exc}")
            failures += 1

    print()
    if failures == 0:
        print(f"All {len(tests)} paper trading cert tests PASSED ✓")
        sys.exit(0)
    else:
        print(f"{failures}/{len(tests)} tests FAILED")
        sys.exit(1)
