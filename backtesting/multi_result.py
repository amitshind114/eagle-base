"""MultiStockResult — Phase 4.

Aggregates individual BacktestResult objects from a multi-symbol run
into a ranked leaderboard and convenience accessors.

Usage:
    from backtesting.multi_result import MultiStockResult

    msr = MultiStockResult(results={"RELIANCE.NS": r1, "TCS.NS": r2})
    print(msr.leaderboard())
    print(msr.best_by_sharpe())
    msr.failed_symbols   # list of symbols that errored
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from backtesting.result import BacktestResult


@dataclass
class MultiStockResult:
    """Aggregated result for a multi-symbol backtest run.

    Attributes:
        results        : Mapping symbol → BacktestResult (successful runs only).
        failed_symbols : Symbols that raised exceptions during the run.
        strategy_name  : Name of the strategy used.
        period         : Period string passed to the runner e.g. '1y', '3y'.
        capital        : Starting capital per symbol.
    """

    results:        dict[str, BacktestResult] = field(default_factory=dict)
    failed_symbols: list[str]                 = field(default_factory=list)
    strategy_name:  str                       = ""
    period:         str                       = ""
    capital:        float                     = 100_000.0

    # ------------------------------------------------------------------
    # Core leaderboard
    # ------------------------------------------------------------------

    def leaderboard(self) -> pd.DataFrame:
        """Return a DataFrame ranked by Sharpe ratio (descending).

        Columns: Symbol, CAGR%, MaxDD%, Sharpe, WinRate%, Trades, Return%
        """
        rows = []
        for symbol, r in self.results.items():
            m = r.metrics
            rows.append({
                "Symbol":   symbol,
                "CAGR%":    round(float(m.get("cagr",          0.0)) * 100, 2),
                "MaxDD%":   round(float(m.get("max_drawdown",  0.0)) * 100, 2),
                "Sharpe":   round(float(m.get("sharpe_ratio",  0.0)),       4),
                "WinRate%": round(float(r.win_rate),                        2),
                "Trades":   int(r.total_trades),
                "Return%":  round(float(r.total_return_pct),                2),
            })

        if not rows:
            return pd.DataFrame(
                columns=["Symbol","CAGR%","MaxDD%","Sharpe","WinRate%","Trades","Return%"]
            )

        df = pd.DataFrame(rows)
        return df.sort_values("Sharpe", ascending=False).reset_index(drop=True)

    def summary_df(self) -> pd.DataFrame:
        """Alias for leaderboard() — included for spec compatibility."""
        return self.leaderboard()

    # ------------------------------------------------------------------
    # Quick accessors
    # ------------------------------------------------------------------

    def best_by_sharpe(self) -> Optional[str]:
        """Return symbol with highest Sharpe ratio, or None if empty."""
        if not self.results:
            return None
        lb = self.leaderboard()
        return str(lb.iloc[0]["Symbol"])

    def best_by_cagr(self) -> Optional[str]:
        """Return symbol with highest CAGR, or None if empty."""
        if not self.results:
            return None
        lb = self.leaderboard().sort_values("CAGR%", ascending=False)
        return str(lb.iloc[0]["Symbol"])

    def worst(self) -> Optional[str]:
        """Return symbol with lowest Sharpe ratio (worst performer)."""
        if not self.results:
            return None
        lb = self.leaderboard()
        return str(lb.iloc[-1]["Symbol"])

    def top_n(self, n: int = 5, metric: str = "Sharpe") -> pd.DataFrame:
        """Return top-N rows from the leaderboard sorted by metric.

        Args:
            n     : Number of rows to return.
            metric: Column to sort by. One of 'Sharpe','CAGR%','WinRate%'.
        """
        lb = self.leaderboard().sort_values(metric, ascending=False)
        return lb.head(n).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def total_symbols(self) -> int:
        return len(self.results) + len(self.failed_symbols)

    @property
    def successful_symbols(self) -> int:
        return len(self.results)

    @property
    def failure_rate(self) -> float:
        if self.total_symbols == 0:
            return 0.0
        return len(self.failed_symbols) / self.total_symbols

    def avg_sharpe(self) -> float:
        if not self.results:
            return 0.0
        values = [float(r.metrics.get("sharpe_ratio", 0.0)) for r in self.results.values()]
        return round(sum(values) / len(values), 4)

    def avg_cagr(self) -> float:
        if not self.results:
            return 0.0
        values = [float(r.metrics.get("cagr", 0.0)) for r in self.results.values()]
        return round(sum(values) / len(values), 4)

    # ------------------------------------------------------------------
    # Text summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        lb = self.leaderboard()
        lines = [
            f"{'='*60}",
            f"  Multi-Stock Result: {self.strategy_name}  |  period={self.period}",
            f"{'='*60}",
            f"  Symbols run    : {self.total_symbols}",
            f"  Successful     : {self.successful_symbols}",
            f"  Failed         : {len(self.failed_symbols)}",
            f"  Avg Sharpe     : {self.avg_sharpe()}",
            f"  Avg CAGR       : {self.avg_cagr()*100:.2f}%",
            f"  Best (Sharpe)  : {self.best_by_sharpe()}",
            f"  Best (CAGR)    : {self.best_by_cagr()}",
            f"  Worst          : {self.worst()}",
            f"{'='*60}",
        ]
        if len(lb) > 0:
            lines.append("  Top 5 by Sharpe:")
            for _, row in lb.head(5).iterrows():
                lines.append(
                    f"    {row['Symbol']:<20}  Sharpe={row['Sharpe']:>6.2f}  "
                    f"CAGR={row['CAGR%']:>6.2f}%  DD={row['MaxDD%']:>6.2f}%"
                )
        if self.failed_symbols:
            lines.append(f"  Failed symbols: {self.failed_symbols}")
        lines.append(f"{'='*60}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"<MultiStockResult strategy='{self.strategy_name}' "
            f"ok={self.successful_symbols} failed={len(self.failed_symbols)}>"
        )
