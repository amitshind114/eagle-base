"""Eagle-Base Portfolio Domain Model.

Tracks capital, margin, exposure, open positions,
closed trades, and equity curve in real time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from domain.position import Position
from domain.trade import Trade
from core.logger import logger


class EquityPoint(BaseModel):
    """Single point on the equity curve."""
    model_config = {"frozen": True}
    timestamp: datetime
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float


class Portfolio(BaseModel):
    """Portfolio: capital tracker + position manager + equity curve.

    - initial_capital: starting cash (immutable after creation)
    - cash: available cash (depleted on buys, increased on sells)
    - open_positions: keyed by symbol
    - closed_trades: historical completed trades
    - equity_curve: sampled over time for performance analysis
    """

    model_config = {"frozen": False, "validate_assignment": True}

    portfolio_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(default="Eagle Portfolio")
    initial_capital: float = Field(..., gt=0)
    cash: float = Field(default=0.0)
    margin_used: float = Field(default=0.0, ge=0)
    max_margin: float = Field(default=0.0, ge=0)
    open_positions: Dict[str, Position] = Field(default_factory=dict)
    closed_trades: List[Trade] = Field(default_factory=list)
    equity_curve: List[EquityPoint] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def model_post_init(self, __context) -> None:
        """Initialise cash to initial_capital on first creation."""
        if self.cash == 0.0:
            self.cash = self.initial_capital
        if self.max_margin == 0.0:
            self.max_margin = self.initial_capital * 0.5  # 50% default margin limit

    # --- Capital Metrics ---

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.open_positions.values())

    @property
    def total_realized_pnl(self) -> float:
        return sum(t.net_pnl for t in self.closed_trades)

    @property
    def equity(self) -> float:
        """Total equity = cash + market value of all open positions."""
        return self.cash + sum(p.current_exposure for p in self.open_positions.values())

    @property
    def total_exposure(self) -> float:
        """Total notional exposure across all open positions."""
        return sum(p.exposure for p in self.open_positions.values())

    @property
    def total_return_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return ((self.equity - self.initial_capital) / self.initial_capital) * 100

    @property
    def margin_utilisation_pct(self) -> float:
        if self.max_margin == 0:
            return 0.0
        return (self.margin_used / self.max_margin) * 100

    @property
    def available_margin(self) -> float:
        return max(0.0, self.max_margin - self.margin_used)

    # --- Position Management ---

    def add_position(self, position: Position) -> None:
        """Register a new open position."""
        if position.symbol in self.open_positions:
            # Add to existing position (scale in)
            existing = self.open_positions[position.symbol]
            existing.add_fill(
                position.quantity,
                position.average_entry_price,
                position.commission_paid,
            )
            logger.info(f"Portfolio: scaled into {position.symbol} position")
        else:
            self.open_positions[position.symbol] = position
            logger.info(f"Portfolio: opened new position {position.symbol}")
        self.cash -= position.exposure
        self.updated_at = datetime.utcnow()

    def close_position(self, symbol: str, exit_price: float, commission: float = 0.0) -> Optional[Trade]:
        """Fully close a position. Returns the resulting Trade."""
        if symbol not in self.open_positions:
            logger.warning(f"Portfolio: no open position found for {symbol}")
            return None
        position = self.open_positions.pop(symbol)
        trade = position.close(exit_price, commission)
        self.closed_trades.append(trade)
        self.cash += trade.quantity * exit_price
        self.updated_at = datetime.utcnow()
        logger.info(f"Portfolio: closed {symbol} trade pnl={trade.net_pnl:.2f}")
        return trade

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Update mark-to-market prices for all open positions."""
        for symbol, price in prices.items():
            if symbol in self.open_positions:
                self.open_positions[symbol].update_last_price(price)
        self.updated_at = datetime.utcnow()

    def snapshot_equity(self, timestamp: Optional[datetime] = None) -> EquityPoint:
        """Record current equity to the equity curve."""
        point = EquityPoint(
            timestamp=timestamp or datetime.utcnow(),
            equity=self.equity,
            cash=self.cash,
            unrealized_pnl=self.total_unrealized_pnl,
            realized_pnl=self.total_realized_pnl,
        )
        self.equity_curve.append(point)
        return point

    # --- Summary ---

    @property
    def win_count(self) -> int:
        return sum(1 for t in self.closed_trades if t.is_winner)

    @property
    def loss_count(self) -> int:
        return sum(1 for t in self.closed_trades if t.is_loser)

    @property
    def win_rate(self) -> float:
        total = len(self.closed_trades)
        if total == 0:
            return 0.0
        return (self.win_count / total) * 100

    @property
    def avg_win(self) -> float:
        winners = [t.net_pnl for t in self.closed_trades if t.is_winner]
        return sum(winners) / len(winners) if winners else 0.0

    @property
    def avg_loss(self) -> float:
        losers = [t.net_pnl for t in self.closed_trades if t.is_loser]
        return sum(losers) / len(losers) if losers else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.net_pnl for t in self.closed_trades if t.is_winner)
        gross_loss = abs(sum(t.net_pnl for t in self.closed_trades if t.is_loser))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    def __str__(self) -> str:
        return (
            f"Portfolio[{self.name}] equity={self.equity:.2f} "
            f"cash={self.cash:.2f} open_positions={len(self.open_positions)} "
            f"closed_trades={len(self.closed_trades)} "
            f"return={self.total_return_pct:.2f}% win_rate={self.win_rate:.1f}%"
        )
