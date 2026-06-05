"""Risk management layer.

Public surface:
    from risk.limits  import risk_limits, RiskLimitBreached
    from risk.gate    import compute_allowed_actions, AllowedAction
    from risk.metrics import compute_metrics
    from risk.sizer   import PositionSizer, SizeResult
"""

from risk.gate    import AllowedAction, compute_allowed_actions
from risk.limits  import RiskLimitBreached, risk_limits
from risk.metrics import compute_metrics
from risk.sizer   import PositionSizer, SizeResult

__all__ = [
    "risk_limits",
    "RiskLimitBreached",
    "compute_allowed_actions",
    "AllowedAction",
    "compute_metrics",
    "PositionSizer",
    "SizeResult",
]
