"""Standardised result envelope used across all modules.

Every public function that can succeed or fail returns a Result so callers
never have to guess the return shape or catch unexpected exceptions.

Usage:
    from core.result import Result, ok, err

    def fetch_data(symbol: str) -> Result:
        try:
            data = ...
            return ok(data)
        except Exception as exc:
            return err(str(exc))

    res = fetch_data("RELIANCE.NS")
    if res.success:
        print(res.data)
    else:
        print(res.error)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Result:
    """Lightweight result container — success or failure, never both."""

    success: bool
    data: Any = field(default=None)
    error: str = field(default="")
    code: str = field(default="")  # optional machine-readable error code

    def __bool__(self) -> bool:
        return self.success

    def unwrap(self) -> Any:
        """Return data or raise RuntimeError if failed."""
        if not self.success:
            raise RuntimeError(self.error or "Result is an error")
        return self.data

    def unwrap_or(self, default: Any) -> Any:
        """Return data if success, else return default."""
        return self.data if self.success else default

    def __repr__(self) -> str:
        if self.success:
            return f"Result.ok(data={type(self.data).__name__})"
        return f"Result.err(error={self.error!r}, code={self.code!r})"


def ok(data: Any = None) -> Result:
    """Construct a successful result."""
    return Result(success=True, data=data)


def err(error: str, code: str = "") -> Result:
    """Construct a failed result."""
    return Result(success=False, error=error, code=code)
