"""Multi-strategy and multi-stock runner — Phase 4 + Phase 9 conflict resolution.

Phase 4: Run one strategy across many symbols (MultiStockRunner).
Phase 9: Run many strategies across same symbols (MultiStrategyRunner).
         Conflict resolution: if two strategies signal OPPOSITE directions
         on the same symbol in the same bar → skip both orders, log WARNING.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.logger import get_logger

log = get_logger("backtesting.multi_runner")


# ── Models ────────────────────────────────────────────────────────────────────

@dataclass
class SymbolResult:
    symbol:       str
    strategy:     str
    total_return: float = 0.0
    sharpe:       float = 0.0
    max_dd:       float = 0.0
    cagr:         float = 0.0
    win_rate:     float = 0.0
    trade_count:  int   = 0
    error:        str   = ""

    @property
    def ok(self) -> bool:
        return self.error == ""


@dataclass
class MultiStockResult:
    """Aggregated results from MultiStockRunner."""
    results: dict[str, SymbolResult] = field(default_factory=dict)

    def leaderboard(self) -> pd.DataFrame:
        """Return a DataFrame sorted by Sharpe descending."""
        rows = [
            {
                "Symbol":   r.symbol,
                "Strategy": r.strategy,
                "CAGR%":    round(r.cagr * 100, 2),
                "MaxDD%":   round(r.max_dd * 100, 2),
                "Sharpe":   round(r.sharpe, 3),
                "WinRate%": round(r.win_rate * 100, 1),
                "Trades":   r.trade_count,
            }
            for r in self.results.values() if r.ok
        ]
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("Sharpe", ascending=False).reset_index(drop=True)

    def best_by_sharpe(self) -> str:
        ok = [r for r in self.results.values() if r.ok]
        return max(ok, key=lambda r: r.sharpe).symbol if ok else ""

    def best_by_cagr(self) -> str:
        ok = [r for r in self.results.values() if r.ok]
        return max(ok, key=lambda r: r.cagr).symbol if ok else ""

    def worst(self) -> str:
        ok = [r for r in self.results.values() if r.ok]
        return min(ok, key=lambda r: r.sharpe).symbol if ok else ""

    def summary_df(self) -> pd.DataFrame:
        return self.leaderboard()


# ── MultiStockRunner (Phase 4) ───────────────────────────────────────────────

class MultiStockRunner:
    """Run one strategy across many symbols independently."""

    def __init__(self, engine=None, data_manager=None) -> None:
        self._engine       = engine
        self._data_manager = data_manager

    def run(
        self,
        strategy,
        symbols: list[str],
        period:  str   = "1y",
        capital: float = 100_000.0,
    ) -> MultiStockResult:
        """Run strategy on each symbol independently.

        One bad symbol never stops the rest.

        Returns:
            MultiStockResult with a SymbolResult per symbol.
        """
        result = MultiStockResult()
        strategy_name = getattr(strategy, "name", strategy.__class__.__name__)

        for sym in symbols:
            log.info(f"[MultiStockRunner] Running {strategy_name} on {sym}...")
            try:
                df = self._fetch(sym, period)
                if df is None or df.empty:
                    raise ValueError(f"No data returned for {sym}")

                signals = strategy.generate_signals(df)
                sr = self._compute_metrics(sym, strategy_name, df, signals, capital)
                result.results[sym] = sr

            except Exception as exc:
                log.warning(f"[MultiStockRunner] {sym} failed: {exc}")
                result.results[sym] = SymbolResult(
                    symbol=sym, strategy=strategy_name, error=str(exc)
                )

        log.info(
            f"[MultiStockRunner] Done: {len(result.results)} symbols, "
            f"{sum(1 for r in result.results.values() if r.ok)} successful."
        )
        return result

    def _fetch(self, symbol: str, period: str) -> pd.DataFrame | None:
        if self._data_manager:
            return self._data_manager.fetch(symbol, period=period, interval="1d")
        try:
            import yfinance as yf
            df = yf.download(symbol if symbol.endswith(".NS") else symbol + ".NS",
                             period=period, interval="1d", progress=False)
            return df
        except Exception as exc:
            log.warning(f"[MultiStockRunner] yfinance fetch failed for {symbol}: {exc}")
            return None

    @staticmethod
    def _compute_metrics(
        symbol: str, strategy_name: str,
        df: pd.DataFrame, signals: pd.Series,
        capital: float,
    ) -> SymbolResult:
        """Compute Sharpe, CAGR, MaxDD, WinRate from signals."""
        import numpy as np

        closes  = df["Close"].squeeze()
        returns = closes.pct_change().fillna(0)

        # Strategy returns: 1=long, -1=short, 0=flat
        strat_returns = signals.shift(1).fillna(0) * returns

        # Sharpe (annualised, 252 trading days)
        mean  = strat_returns.mean()
        std   = strat_returns.std()
        sharpe = (mean / std * (252 ** 0.5)) if std > 0 else 0.0

        # CAGR
        cum     = (1 + strat_returns).cumprod()
        n_years = len(df) / 252
        cagr    = float(cum.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 else 0.0

        # Max drawdown
        roll_max = cum.cummax()
        dd       = (cum - roll_max) / roll_max
        max_dd   = float(dd.min())

        # Win rate
        trades    = signals[(signals != 0) & (signals != signals.shift(1))]
        trade_rets = strat_returns[trades.index]
        win_rate  = float((trade_rets > 0).sum() / len(trade_rets)) if len(trade_rets) else 0.0

        return SymbolResult(
            symbol=symbol,
            strategy=strategy_name,
            total_return=float(cum.iloc[-1] - 1),
            sharpe=round(sharpe, 3),
            max_dd=round(max_dd, 4),
            cagr=round(cagr, 4),
            win_rate=round(win_rate, 4),
            trade_count=len(trades),
        )


# ── MultiStrategyRunner (Phase 9) ─────────────────────────────────────────────

@dataclass
class ConflictRecord:
    symbol:      str
    strategies:  list[str]
    signals:     dict[str, int]   # strategy_name → signal (+1/-1)
    timestamp:   str = ""


@dataclass
class MultiStrategyResult:
    """Result from MultiStrategyRunner.run_all()."""
    signals:   dict[str, dict[str, int]] = field(default_factory=dict)  # sym → {strat → signal}
    conflicts: list[ConflictRecord]      = field(default_factory=list)
    agreed:    dict[str, int]            = field(default_factory=dict)  # sym → consensus signal

    def conflict_count(self) -> int:
        return len(self.conflicts)

    def agreed_symbols(self) -> list[str]:
        return [sym for sym, sig in self.agreed.items() if sig != 0]


class MultiStrategyRunner:
    """Run multiple strategies on the same symbol universe.

    Conflict resolution rule (Phase 9):
      If two or more strategies signal OPPOSITE directions (+1 vs −1)
      for the same symbol in the same bar → skip both (signal = 0), log WARNING.

    If all active strategies agree (all +1 or all −1) → forward the consensus signal.
    If only one strategy has a non-zero signal → forward it.
    """

    def __init__(self, data_manager=None) -> None:
        self._data_manager = data_manager
        self._strategies: list[Any] = []

    def add_strategy(self, strategy) -> None:
        """Register a strategy instance."""
        self._strategies.append(strategy)
        name = getattr(strategy, "name", strategy.__class__.__name__)
        log.info(f"[MultiStrategyRunner] Registered strategy: {name}")

    def run_all(
        self,
        symbols: list[str],
        period:  str = "6mo",
        interval: str = "5m",
    ) -> MultiStrategyResult:
        """Generate signals from all strategies for all symbols.

        Returns MultiStrategyResult with agreed signals and conflict log.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")

        result = MultiStrategyResult()

        for sym in symbols:
            df = self._fetch(sym, period, interval)
            if df is None or df.empty:
                log.warning(f"[MultiStrategyRunner] No data for {sym} — skipping.")
                continue

            # Collect latest signal from each strategy
            sym_signals: dict[str, int] = {}
            for strat in self._strategies:
                name = getattr(strat, "name", strat.__class__.__name__)
                try:
                    sig_series = strat.generate_signals(df)
                    last_sig   = int(sig_series.iloc[-1])
                    sym_signals[name] = last_sig
                except Exception as exc:
                    log.warning(f"[MultiStrategyRunner] {name} failed on {sym}: {exc}")
                    sym_signals[name] = 0

            result.signals[sym] = sym_signals

            # ─ Conflict resolution ─────────────────────────────────────────────────
            active = {k: v for k, v in sym_signals.items() if v != 0}

            if not active:
                result.agreed[sym] = 0
                continue

            unique_directions = set(active.values())

            if len(unique_directions) > 1:
                # Conflict: strategies disagree on direction
                conflicting = [k for k, v in active.items()]
                log.warning(
                    f"[MultiStrategyRunner] CONFLICT on {sym}: "
                    + ", ".join(f"{k}={v:+d}" for k, v in active.items())
                    + " — skipping all orders for this symbol."
                )
                result.conflicts.append(ConflictRecord(
                    symbol=sym,
                    strategies=conflicting,
                    signals=dict(active),
                    timestamp=datetime.now(tz=IST).isoformat(),
                ))
                result.agreed[sym] = 0   # skip

            else:
                # All active strategies agree
                consensus = list(unique_directions)[0]
                result.agreed[sym] = consensus
                log.info(
                    f"[MultiStrategyRunner] {sym}: consensus signal={consensus:+d} "
                    f"from {list(active.keys())}"
                )

        log.info(
            f"[MultiStrategyRunner] Done: {len(symbols)} symbols, "
            f"{len(result.agreed_symbols())} actionable, "
            f"{result.conflict_count()} conflicts skipped."
        )
        return result

    def _fetch(self, symbol: str, period: str, interval: str) -> pd.DataFrame | None:
        if self._data_manager:
            return self._data_manager.fetch(symbol, period=period, interval=interval)
        try:
            import yfinance as yf
            sym = symbol if symbol.endswith(".NS") else symbol + ".NS"
            return yf.download(sym, period=period, interval=interval, progress=False)
        except Exception as exc:
            log.warning(f"[MultiStrategyRunner] fetch failed for {symbol}: {exc}")
            return None
