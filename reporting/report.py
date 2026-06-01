"""Report Generator — Priority 5.

TODO (Phase 4 - Priority 5):
- Generate HTML/PDF backtest report
- Equity curve chart (Plotly)
- Trade log table export
- Summary metrics card
"""

from __future__ import annotations

from core.logger import logger


class ReportGenerator:
    """Generates backtest performance reports."""

    def generate_html(self, result, output_path: str) -> str:
        """Generate HTML report from BacktestResult. TODO: Phase 4 Priority 5."""
        raise NotImplementedError("TODO: Phase 4 Priority 5")

    def export_csv(self, result, output_path: str) -> str:
        """Export trade log to CSV. TODO: Phase 4 Priority 5."""
        raise NotImplementedError("TODO: Phase 4 Priority 5")
