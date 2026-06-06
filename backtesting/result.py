"""Backward-compatibility shim — imports from backtesting.models.

Do NOT add new code here. All real definitions live in backtesting/models.py.
This file exists solely so that legacy imports like:
    from backtesting.result import BacktestResult, Trade
do not break during the transition.
"""

from backtesting.models import BacktestResult, Trade  # noqa: F401

__all__ = ["BacktestResult", "Trade"]
