# Phase 2 — Data + Instruments

## Status: ✅ Complete

---

## Files Built

### `data/` — Priority 1

| File | What it does |
|------|--------------|
| `data/fetcher.py` | `YFinanceProvider` — working OHLCV + quote via yfinance (free, no auth) |
| `data/fetcher.py` | `AngelOneProvider` — skeleton ready, add credentials to `.env` |
| `data/cache.py` | `DataCache` — Parquet-based local file cache (avoids repeat API calls) |
| `data/manager.py` | `DataManager` — unified interface; all modules use this, not fetcher directly |

### `instruments/` — Priority 2

| File | What it does |
|------|--------------|
| `instruments/resolver.py` | `Instrument` dataclass + `InstrumentResolver` with 15 built-in NSE/BSE symbols |
| `instruments/master.py` | `InstrumentMaster` — downloads full Angel One master (~20,000+ instruments) |

### Tests

| File | Coverage |
|------|----------|
| `tests/test_data.py` | YFinanceProvider, DataCache, DataManager |
| `tests/test_instruments.py` | Resolver, search, register, properties, exchange filter |

---

## Run Locally

```bash
# Pull latest
git pull origin main

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/test_data.py tests/test_instruments.py -v

# Smoke test
python -c "
from data.manager import DataManager
from instruments.resolver import InstrumentResolver

m = DataManager()
df = m.get_ohlcv('RELIANCE.NS', '1d', '2024-01-01', '2024-01-10')
print('Data rows:', len(df))
print(df.head())

r = InstrumentResolver()
print(r.resolve('NIFTY'))
print(r.search('TATA'))
"
```

---

## Next: Phase 3 — Backtesting + Strategies

| Module | Priority |
|--------|----------|
| `backtesting/` | 3 |
| `strategies/` | 4 |
