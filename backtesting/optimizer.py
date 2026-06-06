"""ParameterOptimizer — Phase 6.

Finds the best strategy parameters on a given DataFrame by exhaustive
grid search or random sampling, scored by a chosen metric.

Usage:
    from backtesting.optimizer import ParameterOptimizer
    from strategies.ema_crossover import EmaCrossover

    opt = ParameterOptimizer()
    best = opt.optimize(
        strategy_class=EmaCrossover,
        df=train_df,
        params_grid={"fast": [5, 9, 12], "slow": [20, 26, 50]},
        metric="sharpe",
    )
    # → {"fast": 9, "slow": 26}
"""

from __future__ import annotations

import itertools
import random
from typing import Type

import pandas as pd

from core.logger import get_logger
from strategies.base import BaseStrategy

log = get_logger("backtesting.optimizer")

# Supported optimisation metrics and how to extract them from BacktestResult
_METRIC_KEYS = {
    "sharpe":        lambda r: float(r.metrics.get("sharpe_ratio",  0.0)),
    "cagr":          lambda r: float(r.metrics.get("cagr",          0.0)),
    "max_drawdown":  lambda r: -abs(float(r.metrics.get("max_drawdown", 0.0))),  # higher = better (less DD)
    "win_rate":      lambda r: float(r.win_rate),
    "profit_factor": lambda r: float(r.metrics.get("profit_factor", 0.0)),
}


class ParameterOptimizer:
    """Optimise strategy parameters on a fixed training DataFrame.

    Runs all param combinations through BacktestEngine directly
    (no DataManager call — df is pre-loaded).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(
        self,
        strategy_class: Type[BaseStrategy],
        df: pd.DataFrame,
        params_grid: dict,
        metric: str = "sharpe",
        symbol: str = "OPTIMIZE",
        initial_capital: float = 100_000.0,
    ) -> dict:
        """Find best params by grid search.

        Args:
            strategy_class : Uninstantiated strategy class.
            df             : Pre-loaded OHLCV DataFrame (training window).
            params_grid    : Dict of param_name → list of values to try.
            metric         : One of 'sharpe','cagr','max_drawdown','win_rate','profit_factor'.
            symbol         : Symbol name used for BacktestEngine labelling.
            initial_capital: Capital for each trial run.

        Returns:
            Best parameter dict e.g. {"fast": 9, "slow": 26}.
        """
        combos = self.grid_search(params_grid)
        return self._run_trials(strategy_class, df, combos, metric, symbol, initial_capital)

    def random_optimize(
        self,
        strategy_class: Type[BaseStrategy],
        df: pd.DataFrame,
        params_grid: dict,
        n: int = 50,
        metric: str = "sharpe",
        symbol: str = "OPTIMIZE",
        initial_capital: float = 100_000.0,
    ) -> dict:
        """Find best params by random search (faster for large grids).

        Args:
            n: Number of random combinations to try.
        """
        combos = self.random_search(params_grid, n=n)
        return self._run_trials(strategy_class, df, combos, metric, symbol, initial_capital)

    # ------------------------------------------------------------------
    # Combo generators
    # ------------------------------------------------------------------

    def grid_search(self, params_grid: dict) -> list[dict]:
        """Return all combinations of params_grid values.

        Example:
            grid_search({"fast": [5, 9], "slow": [20, 26]})
            → [{"fast":5,"slow":20},{"fast":5,"slow":26},
               {"fast":9,"slow":20},{"fast":9,"slow":26}]
        """
        keys   = list(params_grid.keys())
        values = list(params_grid.values())
        return [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    def random_search(self, params_grid: dict, n: int = 50) -> list[dict]:
        """Return N random combinations sampled from params_grid."""
        all_combos = self.grid_search(params_grid)
        if len(all_combos) <= n:
            return all_combos
        return random.sample(all_combos, n)

    # ------------------------------------------------------------------
    # Trial runner
    # ------------------------------------------------------------------

    def _run_trials(
        self,
        strategy_class: Type[BaseStrategy],
        df: pd.DataFrame,
        combos: list[dict],
        metric: str,
        symbol: str,
        initial_capital: float,
    ) -> dict:
        """Run all combos and return the params with the best metric score."""
        if metric not in _METRIC_KEYS:
            raise ValueError(
                f"Unknown metric '{metric}'. Choose from: {list(_METRIC_KEYS.keys())}"
            )
        score_fn = _METRIC_KEYS[metric]

        from backtesting.engine import BacktestEngine

        best_score  = float("-inf")
        best_params: dict = combos[0] if combos else {}
        results_log: list[tuple[dict, float]] = []

        for params in combos:
            try:
                instance = strategy_class(**params)
                # Validate params if strategy supports it
                if not instance.validate_params(params):
                    continue
                engine = BacktestEngine(
                    symbol=symbol,
                    initial_capital=initial_capital,
                )
                result = engine.run(df, instance)
                score  = score_fn(result)
                results_log.append((params, score))
                if score > best_score:
                    best_score  = score
                    best_params = params
            except Exception as exc:
                log.debug(f"[optimizer] trial {params} failed: {exc}")
                continue

        log.info(
            f"[optimizer] Tried {len(results_log)}/{len(combos)} combos. "
            f"Best {metric}={best_score:.4f} params={best_params}"
        )
        return best_params

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def all_metrics(self) -> list[str]:
        return list(_METRIC_KEYS.keys())
