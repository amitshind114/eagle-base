"""Eagle-Base RiskRule Domain Model.

Defines individual risk control rules and a RiskRuleSet
that runs all rules against an order before it is placed.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from domain.order import Order
from domain.portfolio import Portfolio
from core.logger import logger


class RiskAction(str, Enum):
    BLOCK = "BLOCK"     # Reject the order completely
    WARN = "WARN"       # Allow but log a warning
    ALLOW = "ALLOW"     # Explicitly approved


class RiskRuleResult(BaseModel):
    model_config = {"frozen": True}
    rule_name: str
    action: RiskAction
    reason: str
    triggered: bool


class RiskRule(BaseModel):
    """A single configurable risk rule."""

    model_config = {"frozen": False}

    rule_id: str
    name: str
    description: str = ""
    enabled: bool = True
    action: RiskAction = RiskAction.BLOCK
    parameters: Dict[str, Any] = Field(default_factory=dict)

    def evaluate(self, order: Order, portfolio: Portfolio) -> RiskRuleResult:
        """Subclasses override this method."""
        raise NotImplementedError(f"{self.name}.evaluate() not implemented")


class MaxOrderSizeRule(RiskRule):
    """Block orders that exceed max_order_value (capital notional)."""

    def evaluate(self, order: Order, portfolio: Portfolio) -> RiskRuleResult:
        from domain.enums import OrderType
        max_value = self.parameters.get("max_order_value", 500_000.0)
        if order.price:
            order_value = order.price * order.quantity
        else:
            order_value = order.quantity * 100_000  # conservative estimate for market orders
        triggered = order_value > max_value
        return RiskRuleResult(
            rule_name=self.name,
            action=self.action if triggered else RiskAction.ALLOW,
            reason=(
                f"Order value {order_value:.0f} exceeds max {max_value:.0f}"
                if triggered
                else "OK"
            ),
            triggered=triggered,
        )


class MaxDailyLossRule(RiskRule):
    """Block new orders if daily realized loss exceeds threshold."""

    def evaluate(self, order: Order, portfolio: Portfolio) -> RiskRuleResult:
        max_loss = self.parameters.get("max_daily_loss", 10_000.0)
        daily_loss = abs(min(0.0, portfolio.total_realized_pnl))
        triggered = daily_loss >= max_loss
        return RiskRuleResult(
            rule_name=self.name,
            action=self.action if triggered else RiskAction.ALLOW,
            reason=(
                f"Daily loss {daily_loss:.0f} >= limit {max_loss:.0f}"
                if triggered
                else "OK"
            ),
            triggered=triggered,
        )


class MaxOpenPositionsRule(RiskRule):
    """Block new positions if max open positions already reached."""

    def evaluate(self, order: Order, portfolio: Portfolio) -> RiskRuleResult:
        from domain.enums import OrderSide
        max_positions = self.parameters.get("max_open_positions", 10)
        is_new_position = (
            order.side == OrderSide.BUY
            and order.symbol not in portfolio.open_positions
        )
        triggered = is_new_position and len(portfolio.open_positions) >= max_positions
        return RiskRuleResult(
            rule_name=self.name,
            action=self.action if triggered else RiskAction.ALLOW,
            reason=(
                f"Max open positions {max_positions} already reached"
                if triggered
                else "OK"
            ),
            triggered=triggered,
        )


class ExposureLimitRule(RiskRule):
    """Block if total exposure exceeds max_exposure_pct of initial capital."""

    def evaluate(self, order: Order, portfolio: Portfolio) -> RiskRuleResult:
        max_pct = self.parameters.get("max_exposure_pct", 80.0)
        order_value = (order.price or 0) * order.quantity
        projected_exposure = portfolio.total_exposure + order_value
        max_allowed = portfolio.initial_capital * (max_pct / 100)
        triggered = projected_exposure > max_allowed
        return RiskRuleResult(
            rule_name=self.name,
            action=self.action if triggered else RiskAction.ALLOW,
            reason=(
                f"Projected exposure {projected_exposure:.0f} > limit {max_allowed:.0f} ({max_pct}%)"
                if triggered
                else "OK"
            ),
            triggered=triggered,
        )


class RiskRuleSet(BaseModel):
    """Ordered collection of risk rules. Runs all, returns aggregate result."""

    model_config = {"frozen": False}

    name: str = Field(default="DefaultRuleSet")
    rules: List[RiskRule] = Field(default_factory=list)

    def add_rule(self, rule: RiskRule) -> None:
        self.rules.append(rule)
        logger.debug(f"RiskRuleSet '{self.name}': added rule '{rule.name}'")

    def evaluate(self, order: Order, portfolio: Portfolio) -> Tuple[bool, List[RiskRuleResult]]:
        """Run all enabled rules. Returns (approved: bool, results: list)."""
        results: List[RiskRuleResult] = []
        approved = True
        for rule in self.rules:
            if not rule.enabled:
                continue
            result = rule.evaluate(order, portfolio)
            results.append(result)
            if result.triggered:
                if result.action == RiskAction.BLOCK:
                    approved = False
                    logger.warning(
                        f"RiskRule BLOCK [{rule.name}]: {result.reason} | "
                        f"Order: {order.side.value} {order.quantity} {order.symbol}"
                    )
                elif result.action == RiskAction.WARN:
                    logger.warning(
                        f"RiskRule WARN [{rule.name}]: {result.reason}"
                    )
        return approved, results

    @classmethod
    def default(cls, initial_capital: float = 1_000_000.0) -> "RiskRuleSet":
        """Create a sensible default rule set for a given capital level."""
        rule_set = cls(name="DefaultRuleSet")
        rule_set.add_rule(MaxOrderSizeRule(
            rule_id="max_order_size",
            name="MaxOrderSize",
            description="Block orders exceeding 5% of capital",
            parameters={"max_order_value": initial_capital * 0.05},
        ))
        rule_set.add_rule(MaxDailyLossRule(
            rule_id="max_daily_loss",
            name="MaxDailyLoss",
            description="Block trading after 2% daily loss",
            parameters={"max_daily_loss": initial_capital * 0.02},
        ))
        rule_set.add_rule(MaxOpenPositionsRule(
            rule_id="max_open_positions",
            name="MaxOpenPositions",
            description="Block opening more than 10 positions",
            parameters={"max_open_positions": 10},
        ))
        rule_set.add_rule(ExposureLimitRule(
            rule_id="exposure_limit",
            name="ExposureLimit",
            description="Block if exposure exceeds 80% of capital",
            parameters={"max_exposure_pct": 80.0},
        ))
        return rule_set
