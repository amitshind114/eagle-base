# Phase 3 — Backtesting + Strategies

## Status: ✅ Complete

---

## Files Built

### `backtesting/` — Priority 3

| File | What it does |
|------|--------------|
| `backtesting/engine.py` | `BacktestEngine` — bar-by-bar simulation with commission + slippage |
| `backtesting/runner.py` | `BacktestRunner` — high-level entry point, wires data + engine + strategy |
| `backtesting/result.py` | `BacktestResult` + `Trade` — stores all trades, equity curve, metrics |
| `backtesting/metrics.py` | `MetricsCalculator` — Sharpe, Sortino, Max Drawdown, CAGR, Calmar, Profit Factor |

### `strategies/` — Priority 4

| File | What it does |
|------|--------------|
| `strategies/base.py` | `BaseStrategy` abstract class — all strategies implement `on_bar()` |
| `strategies/sma_crossover.py` | `SMACrossoverStrategy` — SMA 20/50 golden cross / death cross |
| `strategies/rsi_strategy.py` | `RSIStrategy` — RSI 14 oversold/overbought mean reversion |
| `strategies/registry.py` | `StrategyRegistry` — register + load strategies by name |

### Tests

| File | Tests |
|------|-------|
| `tests/test_backtesting.py` | Engine, Result, Metrics — 10 tests |
| `tests/test_strategies.py` | SMA, RSI, Registry — 14 tests |

---

## Run a Full Backtest

```bash
git pull origin main
pip install -r requirements.txt
```

```python
from data.manager import DataManager
from strategies.sma_crossover import SMACrossoverStrategy
from backtesting.runner import BacktestRunner

# Fetch data
dm = DataManager()
df = dm.get_ohlcv("RELIANCE.NS", "1d", "2022-01-01", "2024-12-31")

# Run SMA Crossover backtest
strategy = SMACrossoverStrategy(fast=20, slow=50)
runner = BacktestRunner(
    symbol="RELIANCE.NS",
    strategy=strategy,
    capital=100_000,
    data=df,
)
result = runner.run()
print(result.summary())
print(result.to_trades_df())
```

```python
# RSI Strategy
from strategies.rsi_strategy import RSIStrategy

strategy = RSIStrategy(period=14, oversold=30, overbought=70)
runner = BacktestRunner(symbol="TCS.NS", strategy=strategy, capital=100_000, data=df)
result = runner.run()
print(result.summary())
```

```python
# Use Strategy Registry
from strategies.registry import StrategyRegistry

registry = StrategyRegistry()
strategy = registry.get("sma_crossover", fast=10, slow=30)
print(registry.names())
```

## Run Tests

```bash
pytest tests/test_backtesting.py tests/test_strategies.py -v
```

---

## Metrics Explained

| Metric | Description |
|--------|-------------|
| `sharpe_ratio` | Risk-adjusted return (India RF = 6.5%) |
| `sortino_ratio` | Sharpe but penalises only downside volatility |
| `max_drawdown_pct` | Largest peak-to-trough drop (%) |
| `cagr_pct` | Compound Annual Growth Rate (%) |
| `calmar_ratio` | CAGR / Max Drawdown |
| `profit_factor` | Gross profit / Gross loss |
| `expectancy` | Average PnL per trade |

---

## Next: Phase 4 — Reporting + Risk + Paper + UI

| Module | Priority |
|--------|----------|
| `reporting/` | 5 |
| `risk/` | 6 |
| `paper/` | 7 |
| `ui/` | 8 |
