# Eagle-Base

Algorithmic Research & Trading System — built in 4 phases.

## Build Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Architecture Generation — structure, modules, interfaces | ✅ Done |
| 2 | GitHub Repository — push generated structure | ✅ Done |
| 3 | VS Code Local Build — Python, Ruff, Black, Pylance | 🔄 Next |
| 4 | Incremental Build — module by module | ⏳ Pending |

## Build Priority (Phase 4)

1. Data
2. Instrument Resolution
3. Backtesting
4. Strategy Plugins
5. Reporting
6. Risk
7. Paper Execution
8. AI
9. Derivatives
10. Live Execution

## Project Structure

```
eagle-base/
├── core/            # Shared base classes, config, logging
├── data/            # Data fetching, storage, feeds
├── instruments/     # Instrument resolution & metadata
├── backtesting/     # Backtesting engine
├── strategies/      # Strategy plugin system
├── reporting/       # Reports, charts, exports
├── risk/            # Risk management & controls
├── paper/           # Paper trading execution
├── ai/              # AI/ML integration
├── derivatives/     # Options, futures, derivatives logic
├── live/            # Live execution engine
├── api/             # REST API layer (FastAPI)
├── ui/              # Streamlit dashboard UI
├── tests/           # All unit and integration tests
└── docs/            # Architecture docs
```

## Quick Start

```bash
# Clone
gh repo clone amitshind114/eagle-base
cd eagle-base

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run app
streamlit run ui/app.py
```

## Stack
- Python 3.11+
- FastAPI + Uvicorn (API)
- Streamlit (UI)
- Pandas, NumPy (Data)
- Angel One SmartAPI (Broker)
- Ruff + Black + Pylance (Code Quality)
