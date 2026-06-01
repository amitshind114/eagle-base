# Eagle-Base Architecture

## Overview

Eagle-Base is a modular algorithmic research and trading system built in Python.
It follows a clean layered architecture with clear separation between data, logic, execution, and UI.

## Module Map

```
┌─────────────────────────────────────────────┐
│                 UI (Streamlit)              │
├─────────────────────────────────────────────┤
│              API (FastAPI)                  │
├───────────┬──────────┬──────────┬───────────┤
│   Data    │Instruments│Strategies│ Reporting │
├───────────┼──────────┼──────────┼───────────┤
│  Backtest │   Risk   │  Paper   │    AI     │
├───────────┼──────────┼──────────┼───────────┤
│      Derivatives     │  Live Execution       │
├─────────────────────────────────────────────┤
│                Core (base, config, logger)  │
└─────────────────────────────────────────────┘
```

## Build Order (Phase 4)

| Priority | Module | Status |
|----------|--------|--------|
| 1 | Data | Scaffolded |
| 2 | Instruments | Scaffolded |
| 3 | Backtesting | Scaffolded |
| 4 | Strategies | Scaffolded |
| 5 | Reporting | Scaffolded |
| 6 | Risk | Scaffolded |
| 7 | Paper Execution | Scaffolded |
| 8 | AI | Scaffolded |
| 9 | Derivatives | Scaffolded |
| 10 | Live Execution | Disabled |

## Data Flow

```
Market Data → Data Module → Instrument Resolver
                                    ↓
                            Strategy Plugins
                                    ↓
                          Backtesting Engine
                                    ↓
                    Risk Manager → Paper Executor
                                    ↓
                    Reporting → Dashboard (UI)
```

## Rules

1. Never import from `live/` in any module except `api/`.
2. `LIVE_ENABLED = False` by default in `live/executor.py`.
3. All secrets via `.env` — never hardcode credentials.
4. All modules must pass `ruff` and `black` before PR.
