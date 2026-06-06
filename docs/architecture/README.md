# Eagle-Base — Architecture Documentation

> **Version**: v0.3.0 · **Commit**: 1179f6e · **Updated**: 2026-06-07

This directory contains BPMN swimlane diagrams describing the complete trading lifecycle.
Diagrams are split into 3 phases for readability.

---

## System Overview

Eagle-Base is a modular algorithmic trading platform built on:

| Layer | Technology |
|---|---|
| UI | Streamlit 1.x (multi-page) |
| API | FastAPI + Uvicorn |
| Engine | `live/engine.py` → `live/runner.py` (singleton + per-strategy threads) |
| Broker | `brokers/adapters/` — Angel One, Zerodha, Upstox, Fyers, IIFL |
| Paper | `paper/portfolio.py` — virtual fill engine |
| Risk | `risk/gate.py` + `risk/limits.py` — pre-trade VaR + daily cap |
| Audit | `core/audit.py` — 200-event ring buffer + structured log |
| Strategies | `strategies/` — registry pattern, `on_bar(bar) → signal` |

---

## Phase Diagrams

### Phase 1 — Research, Backtest & Risk Gate

**File**: `phase1_research_risk.png` / `.svg`

```
Streamlit UI  → Select Strategy from registry
             → Set Parameters (capital · symbol · mode)
             → POST /api/backtest/run
FastAPI       → Engine simulation → GET /api/backtest/results
UI            → Review metrics (Sharpe · MDD · CAGR)
             → [No] → retry params
             → [Yes] → Risk Module
Risk Gate     → VaR check + Position Sizing
             → [No] → HTTP 400 FAIL
             → [Yes] → PASS → ready for deployment
```

**Key safety rule**: Strategy cannot be deployed until it passes BOTH:
1. User approval (metrics look acceptable)
2. Risk gate (VaR within limits, position sizing valid)

---

### Phase 2 — Deploy & Signal Execution Loop

**File**: `phase2_deploy_signal.png` / `.svg`

```
API           → POST /api/live/deploy  (LIVE mode)
             → POST /api/paper/signal  (PAPER mode)
LiveEngine    → LiveEngine.deploy() → StrategyRunner created
Runner        → background thread starts, tick loop begins
             → strategy.on_bar(bar) every 60s (configurable)
             → Pre-trade risk re-check (VaR · drawdown gate)
             → [Pass + LIVE]  → place_order() → Angel One SmartAPI
             → [Pass + PAPER] → PaperExecutorStub.place_order()
Broker        → FILLED callback → PositionBook.update()
Dashboard     → GET /api/live/status · /positions · /orders
             → [No exit condition] → next bar loop
             → [Exit condition]    → Phase 3
```

**Key safety rules**:
- `EAGLE_LIVE_ENABLED=false` (default) blocks all live deploys
- Pre-trade risk check runs on EVERY bar, not just at deploy time
- Idempotency key prevents duplicate orders on retry
- Circuit breaker opens after 3 consecutive broker failures

---

### Phase 3 — Kill Switch, Square-off & Audit

**File**: `phase3_kill_audit.png` / `.svg`

```
UI            → Kill Switch panel — user types CONFIRM
API           → POST /api/live/kill/strategies  {"confirm": "CONFIRM"}
             → POST /api/live/kill/orders       {"confirm": "CONFIRM"}
             → POST /api/live/kill/positions    {"confirm": "CONFIRM"}
             → [Wrong/missing confirm] → HTTP 400 immediately, NO side effects
LiveEngine    → kill_all_strategies() — stops all StrategyRunners
             → cancel_all_orders()    — cancels pending orders at exchange
             → square_off_all()       — MKT SELL/BUY all open positions
Broker        → Execute cancel + square-off orders
Audit         → KILL_* event written to ring buffer (ts · action · result)
UI            → Audit Tab refresh via GET /api/live/audit
```

**Key safety rules**:
- `confirm` body field is **case-sensitive**: `"CONFIRM"` only
- All 3 kill routes are independent — can be called in any order
- Square-off uses best-effort LTP (yfinance fallback if Angel One unavailable)
- Every kill action is timestamped and written to audit log regardless of outcome

---

## Module Dependency Map

```
api/routers/live.py
    └── live/engine.py          ← LiveEngine singleton
            └── live/runner.py  ← StrategyRunner (1 per deployed strategy)
                    ├── strategies/registry.py  ← get_strategy_class(id)
                    │       └── strategies/ema_cross.py  ← EMACrossStrategy
                    ├── live/executor.py        ← LiveExecutor (real broker)
                    │       └── brokers/adapters/angelone.py
                    ├── paper/portfolio.py      ← PaperExecutorStub (paper mode)
                    ├── risk/gate.py            ← compute_allowed_actions()
                    └── core/audit.py           ← audit.record()
```

---

## Environment Variables

| Variable | Default | Required for |
|---|---|---|
| `EAGLE_LIVE_ENABLED` | `false` | Live trading |
| `ANGEL_API_KEY` | — | Angel One auth |
| `ANGEL_CLIENT_ID` | — | Angel One auth |
| `ANGEL_PASSWORD` | — | Angel One auth |
| `ANGEL_TOTP_SECRET` | — | Angel One TOTP |
| `EAGLE_TICK_INTERVAL` | `60` | Bar frequency (seconds) |
| `EAGLE_DATA_DIR` | `eagle_base/data` | SQLite + JSON storage |

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Kill switch guard only
pytest tests/test_kill_guard.py -v

# Live router only
pytest tests/test_live_router.py -v

# With coverage
pytest tests/ --cov=live --cov=strategies --cov-report=term-missing
```

---

## Next Steps

- [ ] `instruments/token_map.py` — Angel One symbol → token resolution
- [ ] Angel One live auth end-to-end test with real credentials
- [ ] WebSocket market feed integration (replace yfinance tick fallback)
- [ ] `strategies/rsi_mean_revert.py` — second strategy
- [ ] Telegram / email alert integration on KILL events
- [ ] Docker + systemd service for production deployment
