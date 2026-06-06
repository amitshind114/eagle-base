"""WalkForwardTester — Phase 6.

Rolling walk-forward analysis:
  For each window:
    1. Train  → optimise params on training period
    2. Validate → score best params on validation period  (optional early stop)
    3. Forward → run on unseen forward period → OOS result

Window layout (months):
  |<---- train_months ---->|<- validate_months ->|<- forward_months ->|
  Slide by forward_months each iteration for n_windows total windows.

Key output: WalkForwardResult with per-window IS vs OOS metrics
and a stitched OOS equity curve.

Usage:
    from backtesting.walk_forward import WalkForwardTester
    from strategies.ema_crossover import EmaCrossover

    wft = WalkForwardTester()
    result = wft.run(
        strategy_class=EmaCrossover,
        params_grid={"fast": [5, 9, 12], "slow": [20, 26, 50]},
        symbol="RELIANCE.NS",
        from_date="2018-01-01",
        to_date="2024-12-31",
        train_months=12,
        validate_months=3,
        forward_months=3,
        metric="sharpe",
    )
    print(result.summary())
    print(result.efficiency_ratio())
    print(result.is_robust())
"""

from __future__ import annotations

from datetime import date
from dateutil.relativedelta import relativedelta
from typing import Type

import pandas as pd

from core.logger import get_logger
from backtesting.optimizer import ParameterOptimizer
from backtesting.wf_result import WalkForwardResult, WFWindow
from strategies.base import BaseStrategy

log = get_logger("backtesting.walk_forward")


class WalkForwardTester:
    """Rolling walk-forward analyser.

    Args:
        optimizer: ParameterOptimizer instance (default: new instance).
        n_random : If set, use random_search with this many combos instead
                   of full grid search (faster for large grids).
    """

    def __init__(
        self,
        optimizer: ParameterOptimizer | None = None,
        n_random: int | None = None,
    ) -> None:
        self.optimizer = optimizer or ParameterOptimizer()
        self.n_random  = n_random

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        strategy_class: Type[BaseStrategy],
        params_grid: dict,
        symbol: str,
        from_date: str        = "2018-01-01",
        to_date: str          = "2024-12-31",
        train_months: int     = 12,
        validate_months: int  = 3,
        forward_months: int   = 3,
        metric: str           = "sharpe",
        interval: str         = "1d",
        initial_capital: float = 100_000.0,
    ) -> WalkForwardResult:
        """Run rolling walk-forward analysis.

        Args:
            strategy_class  : Uninstantiated strategy class.
            params_grid     : Param search space e.g. {"fast":[5,9,12],"slow":[20,26]}.
            symbol          : Yahoo Finance symbol e.g. 'RELIANCE.NS'.
            from_date       : Full dataset start date (YYYY-MM-DD).
            to_date         : Full dataset end date (YYYY-MM-DD).
            train_months    : IS training window length in months.
            validate_months : Validation window length in months.
            forward_months  : OOS forward window length in months.
            metric          : Optimisation metric ('sharpe','cagr','win_rate',...).
            interval        : OHLCV bar interval.
            initial_capital : Capital for each trial run.

        Returns:
            WalkForwardResult with per-window stats and stitched OOS equity.
        """
        log.info(
            f"[wf] START {strategy_class.__name__} on {symbol} "
            f"{from_date}→{to_date} train={train_months}m val={validate_months}m "
            f"fwd={forward_months}m metric={metric}"
        )

        # Fetch full dataset once
        full_df = self._fetch(symbol, from_date, to_date, interval)
        if full_df.empty:
            log.error(f"[wf] No data for {symbol}")
            return WalkForwardResult(symbol=symbol, strategy_name=strategy_class.name)

        # Build windows
        windows_meta = self._build_windows(
            from_date=from_date,
            to_date=to_date,
            train_months=train_months,
            validate_months=validate_months,
            forward_months=forward_months,
        )

        if not windows_meta:
            log.warning("[wf] No windows fit in the given date range.")
            return WalkForwardResult(symbol=symbol, strategy_name=strategy_class.name)

        log.info(f"[wf] Running {len(windows_meta)} windows")

        wf_windows:  list[WFWindow] = []
        fwd_equities: list[pd.Series] = []

        for i, meta in enumerate(windows_meta, start=1):
            win = self._run_window(
                window_id=i,
                meta=meta,
                full_df=full_df,
                strategy_class=strategy_class,
                params_grid=params_grid,
                metric=metric,
                symbol=symbol,
                initial_capital=initial_capital,
            )
            wf_windows.append(win)
            if len(win.forward_equity) > 0:
                fwd_equities.append(win.forward_equity)
            log.info(
                f"[wf] Window {i}/{len(windows_meta)}: "
                f"IS={win.train_score:.3f} OOS={win.forward_score:.3f} "
                f"params={win.best_params}"
            )

        # Stitch OOS equity curves
        combined_equity = self._stitch_equity(fwd_equities, initial_capital)

        result = WalkForwardResult(
            windows=wf_windows,
            combined_forward_equity=combined_equity,
            symbol=symbol,
            strategy_name=strategy_class.name,
            metric=metric,
        )

        log.info(
            f"[wf] DONE efficiency={result.efficiency_ratio():.2f} "
            f"robust={result.is_robust()}"
        )
        return result

    # ------------------------------------------------------------------
    # Window builder
    # ------------------------------------------------------------------

    def _build_windows(
        self,
        from_date: str,
        to_date: str,
        train_months: int,
        validate_months: int,
        forward_months: int,
    ) -> list[dict]:
        """Compute date boundaries for each rolling window."""
        start      = date.fromisoformat(from_date)
        end        = date.fromisoformat(to_date)
        total_window = train_months + validate_months + forward_months
        windows    = []
        cursor     = start

        while True:
            train_s    = cursor
            train_e    = cursor + relativedelta(months=train_months) - relativedelta(days=1)
            val_s      = train_e + relativedelta(days=1)
            val_e      = val_s   + relativedelta(months=validate_months) - relativedelta(days=1)
            fwd_s      = val_e   + relativedelta(days=1)
            fwd_e      = fwd_s   + relativedelta(months=forward_months) - relativedelta(days=1)

            if fwd_e > end:
                break

            windows.append({
                "train_start":    str(train_s),
                "train_end":      str(train_e),
                "validate_start": str(val_s),
                "validate_end":   str(val_e),
                "forward_start":  str(fwd_s),
                "forward_end":    str(fwd_e),
            })
            cursor += relativedelta(months=forward_months)

        return windows

    # ------------------------------------------------------------------
    # Single window runner
    # ------------------------------------------------------------------

    def _run_window(
        self,
        window_id: int,
        meta: dict,
        full_df: pd.DataFrame,
        strategy_class: Type[BaseStrategy],
        params_grid: dict,
        metric: str,
        symbol: str,
        initial_capital: float,
    ) -> WFWindow:
        """Run one train/validate/forward window."""
        train_df    = self._slice(full_df, meta["train_start"],    meta["train_end"])
        val_df      = self._slice(full_df, meta["validate_start"], meta["validate_end"])
        forward_df  = self._slice(full_df, meta["forward_start"],  meta["forward_end"])

        # --- Optimise on train ---
        if self.n_random:
            best_params = self.optimizer.random_optimize(
                strategy_class, train_df, params_grid,
                n=self.n_random, metric=metric,
                symbol=symbol, initial_capital=initial_capital,
            )
        else:
            best_params = self.optimizer.optimize(
                strategy_class, train_df, params_grid,
                metric=metric, symbol=symbol, initial_capital=initial_capital,
            )

        # --- Score on train (IS) ---
        train_result = self._score(strategy_class, best_params, train_df, symbol, initial_capital)
        train_score  = self._extract_metric(train_result, metric)
        train_ret    = train_result.total_return_pct if train_result else 0.0

        # --- Score on validate ---
        val_result   = self._score(strategy_class, best_params, val_df, symbol, initial_capital)
        val_score    = self._extract_metric(val_result, metric)

        # --- Score on forward (OOS) ---
        fwd_result   = self._score(strategy_class, best_params, forward_df, symbol, initial_capital)
        fwd_score    = self._extract_metric(fwd_result, metric)
        fwd_ret      = fwd_result.total_return_pct if fwd_result else 0.0
        fwd_equity   = (
            pd.Series(fwd_result.equity_curve, dtype=float)
            if fwd_result and fwd_result.equity_curve
            else pd.Series(dtype=float)
        )

        return WFWindow(
            window_id=window_id,
            train_start=meta["train_start"],
            train_end=meta["train_end"],
            validate_start=meta["validate_start"],
            validate_end=meta["validate_end"],
            forward_start=meta["forward_start"],
            forward_end=meta["forward_end"],
            best_params=best_params,
            train_score=train_score,
            validate_score=val_score,
            forward_score=fwd_score,
            train_return=train_ret,
            forward_return=fwd_ret,
            forward_equity=fwd_equity,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch(
        self, symbol: str, from_date: str, to_date: str, interval: str
    ) -> pd.DataFrame:
        try:
            from data.manager import DataManager
            return DataManager().get_ohlcv(symbol, interval, from_date, to_date)
        except Exception as exc:
            log.error(f"[wf] Fetch failed: {exc}")
            return pd.DataFrame()

    def _slice(
        self, df: pd.DataFrame, start: str, end: str
    ) -> pd.DataFrame:
        """Return rows of df within [start, end] inclusive."""
        if df.empty:
            return df
        mask = (df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))
        return df.loc[mask]

    def _score(self, strategy_class, params, df, symbol, capital):
        """Run engine on df with given params, return BacktestResult or None."""
        if df.empty:
            return None
        try:
            from backtesting.engine import BacktestEngine
            instance = strategy_class(**params)
            engine   = BacktestEngine(symbol=symbol, initial_capital=capital)
            return engine.run(df, instance)
        except Exception as exc:
            log.debug(f"[wf] Score failed {params}: {exc}")
            return None

    def _extract_metric(self, result, metric: str) -> float:
        if result is None:
            return 0.0
        from backtesting.optimizer import _METRIC_KEYS
        fn = _METRIC_KEYS.get(metric)
        if fn is None:
            return 0.0
        try:
            return fn(result)
        except Exception:
            return 0.0

    def _stitch_equity(
        self, equities: list[pd.Series], initial_capital: float
    ) -> pd.Series:
        """Chain OOS equity curves end-to-end into one continuous series.

        Each window's curve is rebased to start where the previous window ended.
        """
        if not equities:
            return pd.Series(dtype=float)

        stitched: list[float] = [initial_capital]
        running_capital = initial_capital

        for eq in equities:
            if eq.empty:
                continue
            eq_arr = eq.values
            # Scale this window relative to where we ended
            if eq_arr[0] == 0:
                continue
            scale = running_capital / eq_arr[0]
            scaled = eq_arr * scale
            stitched.extend(scaled.tolist())
            running_capital = scaled[-1]

        return pd.Series(stitched, dtype=float)
