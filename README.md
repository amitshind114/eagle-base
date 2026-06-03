# 🦅 Eagle-Base v0.1.0

**Algorithmic Research & Trading System**

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/amitshind114/eagle-base.git
cd eagle-base

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy env file
copy .env.example .env

# 5. Run Streamlit UI
python -m streamlit run ui/app.py

# 6. (Optional) Run FastAPI backend
uvicorn api.main:app --reload --port 8000

# 7. Run tests
pytest tests/ -v
```

---

## Project Structure

```
eagle-base/
├── core/              # Config, logger, exceptions
├── data/              # yfinance fetcher, OHLCV models
├── instruments/       # NSE/BSE registry, symbol resolution
├── backtesting/       # Engine, results model
├── strategies/        # SMA, EMA, RSI, MACD signal generators
├── reporting/         # PnL, trade stats, export
├── risk/              # Position sizer, VaR, limit checks
├── paper/             # Order simulator, portfolio tracker
├── ai/                # Signal scanner, multi-indicator analysis
├── derivatives/       # Black-Scholes options chain, Greeks
├── live/              # 🔒 Locked — post paper validation
├── api/               # FastAPI REST backend
├── ui/                # Streamlit dashboard (app.py)
├── tests/             # pytest test suite
├── .vscode/           # VS Code settings, launch configs
├── pyproject.toml     # Black + Ruff + pytest config
├── pyrightconfig.json # Pylance type checking config
└── requirements.txt
```

---

## Module Status

| Module | Status | Description |
|---|---|---|
| 🏠 Home | ✅ Live | Market heatmap, module overview |
| 📊 Data | ✅ Live | yfinance OHLCV, candlestick charts |
| 🔍 Instruments | ✅ Live | NSE/BSE search, sector filter, comparison |
| ⚙️ Backtesting | ✅ Live | SMA/EMA/RSI/MACD, equity curve, metrics |
| 🧩 Strategies | ✅ Live | Plugin registry, param editor |
| 📈 Reporting | ✅ Live | PnL, drawdown, trade log, export |
| 🛡️ Risk | ✅ Live | Position sizer, VaR, limit dashboard |
| 📋 Paper Trading | ✅ Live | Order sim, portfolio tracker, order history |
| 🤖 AI | ✅ Live | Signal scanner, RSI/MACD/BB/Volume |
| 📐 Derivatives | ✅ Live | Options chain, Greeks, payoff diagram |
| ⚡ Live | 🔒 Locked | Enable after 30-day paper validation |

---

## VS Code Setup

1. Open folder in VS Code
2. Install recommended extensions (prompted automatically via `.vscode/extensions.json`)
3. Select interpreter: `.venv\Scripts\python.exe`
4. Use **Run & Debug** → `Run Streamlit App` to launch
5. Ruff and Black auto-format on save

---

## Tech Stack

- **UI**: Streamlit 1.58 + Plotly 6
- **Data**: yfinance, pandas, numpy
- **API**: FastAPI + uvicorn
- **Options**: scipy (Black-Scholes)
- **Linting**: Ruff + Black
- **Types**: Pylance + Pyright (basic mode)
- **Tests**: pytest + pytest-cov
