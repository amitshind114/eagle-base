# Phase 06 — Paper Trading: Manual Validation Guide

This document covers **Task 7** — the 5-day paper trading validation run and the three kill/restart integrity checks required before proceeding to Phase 7 (Strategy Registry).

---

## Prerequisites

1. Phase 1 instruments DB refreshed: `python -m instruments.downloader`
2. DataFetcher configured and able to pull 5m data
3. All 6 cert tests passing: `python tests/cert_paper.py`

---

## 5-Day Run Procedure

### Day 1 — Fresh start
```bash
python scripts/paper_run.py --fresh --days 5
# Let it run. Ctrl+C after at least 20 bars have processed.
```

### Kill/Restart Test (repeat 3 times)
```bash
# 1. Record snapshot BEFORE kill
python -c "
from paper.portfolio import PaperPortfolio
p = PaperPortfolio(); p.restore()
snap = p.snapshot()
print(f'BEFORE: cash={snap.cash:.0f} positions={snap.open_positions} trades={snap.total_trades}')
"

# 2. Kill the running process (Ctrl+C or kill -9 <pid>)

# 3. Restart
python scripts/paper_run.py --days 5

# 4. Record snapshot AFTER restart
python -c "
from paper.portfolio import PaperPortfolio
p = PaperPortfolio(); p.restore()
snap = p.snapshot()
print(f'AFTER:  cash={snap.cash:.0f} positions={snap.open_positions} trades={snap.total_trades}')
"

# 5. Compare BEFORE and AFTER — must be identical
```

---

## Daily Checks (each of 5 days)

### Check 1 — position_book == trade_book
```python
from paper.portfolio import PaperPortfolio
from paper.models import OrderSide
from collections import defaultdict

p = PaperPortfolio()
p.restore()
assert not p.is_corrupted, "CORRUPTED state detected!"

net_qty = defaultdict(int)
for t in p.trade_book.all():
    if t.side == OrderSide.BUY:
        net_qty[t.symbol] += t.quantity
    else:
        net_qty[t.symbol] -= t.quantity

for pos in p.position_book.all_open():
    expected = net_qty.get(pos.symbol, 0)
    assert pos.quantity == expected, (
        f"MISMATCH {pos.symbol}: position={pos.quantity}, trade_net={expected}"
    )
print("CHECK 1 PASSED: position_book matches trade_book")
```

### Check 2 — No stale positions after restart
All positions in `position_book.all_open()` must have a net positive quantity from the trade log.  The `_verify_integrity()` call inside `restore()` enforces this automatically.  If `is_corrupted == True`, do NOT proceed — see Reconciliation below.

### Check 3 — Manual PnL spot-check
Pick 2–3 trades from `trade_book.today()` and calculate PnL manually:
```
REALIZED per trade:
  BUY  qty=10 @ 2500  →  cost = 25000
  SELL qty=10 @ 2600  →  proceeds = 26000
  realized_pnl = 26000 - 25000 = 1000

UNREALIZED per position:
  qty=5, avg_cost=2500, current_price=2650
  unrealized = 5 * (2650 - 2500) = 750

DAILY PnL = sum(realized today) + unrealized = 1000 + 750 = 1750
```
Compare against `portfolio.daily_pnl()`.  Tolerance: ±0.01 (floating point).

---

## Exit Gate Checklist

- [ ] `portfolio.snapshot()` before restart == `portfolio.snapshot()` after restart (×3)
- [ ] `position_book.get(sym).quantity == sum(BUY) - sum(SELL)` for every symbol
- [ ] `final_capital = initial_cash + sum(all trade PnLs) - sum(all charges)`
- [ ] 5-day paper run with zero `AttributeError` and zero `corrupted=True`
- [ ] Daily reports written to `logs/daily_report_YYYYMMDD.txt` for all 5 days

---

## Corruption Recovery

If `is_corrupted == True`:

1. Do NOT run any new strategies
2. Open `eagle_base/data/paper_portfolio.db` in SQLite Browser
3. Run: `SELECT symbol, SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END) as net FROM trades GROUP BY symbol`
4. Compare with `SELECT * FROM positions`
5. Fix the `positions` table to match trade-derived net quantities
6. Set `_corrupted = False` by re-running `portfolio.restore()` after the fix
