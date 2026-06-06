"""StrategyMeta dataclass — Phase 7.

Every registered strategy exposes this metadata.
Used by:
  - StrategyRegistry  → list, filter, search
  - UI (Strategies page) → display name/version/tags/status/last result
  - MultiStockRunner  → identify strategy name for leaderboard
  - WalkForwardTester → version stamp per window

Usage:
    from strategies.meta import StrategyMeta
    meta = StrategyMeta(
        name="EMA Crossover",
        version="1.1.0",
        author="eagle",
        description="Fast/slow EMA crossover",
        parameters={"fast": 12, "slow": 26},
        tags=["trend", "daily"],
        status="active",
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class StrategyMeta:
    """Metadata descriptor for a registered strategy.

    Attributes:
        name        : Human-readable strategy name. e.g. "EMA Crossover"
        version     : Semantic version string. e.g. "1.1.0"
        author      : Creator / owner. e.g. "eagle", your name
        description : One-line description shown in the UI.
        parameters  : Default parameter dict. e.g. {"fast": 12, "slow": 26}
        tags        : Category labels for filtering. e.g. ["trend", "intraday"]
        status      : Lifecycle stage — "active" | "testing" | "draft" | "retired"
        last_result : Most recent BacktestResult. None until first backtest run.
        created_at  : When the strategy was first registered.
        updated_at  : When the strategy or its result was last updated.
    """

    name:        str
    version:     str
    author:      str
    description: str
    parameters:  dict[str, Any]         = field(default_factory=dict)
    tags:        list[str]              = field(default_factory=list)
    status:      str                    = "active"   # active | testing | draft | retired
    last_result: Optional[Any]          = None        # BacktestResult | None
    created_at:  datetime               = field(default_factory=datetime.utcnow)
    updated_at:  datetime               = field(default_factory=datetime.utcnow)

    # ── Validation ─────────────────────────────────────────────────────

    _VALID_STATUSES = {"active", "testing", "draft", "retired"}

    def __post_init__(self) -> None:
        if self.status not in self._VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{self.status}'. "
                f"Must be one of: {sorted(self._VALID_STATUSES)}"
            )

    # ── Helpers ─────────────────────────────────────────────────────────

    def touch(self) -> None:
        """Update the updated_at timestamp. Call after storing a new result."""
        self.updated_at = datetime.utcnow()

    def has_result(self) -> bool:
        """Return True if at least one backtest result has been stored."""
        return self.last_result is not None

    def to_dict(self) -> dict:
        """Serialise to a plain dict (for UI / API responses)."""
        return {
            "name":        self.name,
            "version":     self.version,
            "author":      self.author,
            "description": self.description,
            "parameters":  self.parameters,
            "tags":        self.tags,
            "status":      self.status,
            "has_result":  self.has_result(),
            "created_at":  self.created_at.isoformat(),
            "updated_at":  self.updated_at.isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"<StrategyMeta name='{self.name}' v{self.version} "
            f"status='{self.status}' tags={self.tags}>"
        )
