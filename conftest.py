"""Root conftest.py — Phase 3.

Ensures the repository root is on sys.path so all packages
(backtesting/, instruments/, core/, etc.) are importable when
pytest is invoked from any working directory — locally or in CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Insert repo root at the front of the import path
ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
