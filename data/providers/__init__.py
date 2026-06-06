"""Provider abstraction layer — Phase 3.

Exports the abstract base and all concrete providers.
Strategies and engines NEVER import from here directly;
they use DataManager which picks the right provider.

Usage:
    from data.providers import DataProvider
    from data.providers.yahoo import YahooProvider
    from data.providers.csv import CSVProvider
    from data.providers.parquet import ParquetProvider
"""

from .base import DataProvider
from .yahoo import YahooProvider
from .angel import AngelProvider
from .csv import CSVProvider
from .parquet import ParquetProvider

__all__ = [
    "DataProvider",
    "YahooProvider",
    "AngelProvider",
    "CSVProvider",
    "ParquetProvider",
]
