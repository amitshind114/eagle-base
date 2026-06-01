"""Eagle-Base Domain Model Test Suite.

Tests:
- Instrument validation (EQ, FUT, CE, PE, INDEX)
- Candle OHLC validation and derived properties
- Signal creation and risk/reward
- Order lifecycle and state transitions
- Trade PnL calculations
- Position add/close with PnL validation
- Portfolio capital tracking
- BacktestResult metrics computation
- RiskRuleSet evaluation

Run with: pytest tests/test_domain.py -v
"""

from __future__ import annotations

from datetime import datetime, date
from typing import List

import pytest

from domain import (
    Instrument, Candle, Signal, Order, Trade, Position, Portfolio,
    StrategyContext, BacktestResult, RiskRule, RiskRuleSet,
    Exchange, InstrumentType, OptionType, OrderSide, OrderType,
    OrderStatus, SignalDirection, PositionSide, TimeInForce,
)
from domain.risk_rule import (
    MaxOrderSizeRule, MaxDailyLossRule, MaxOpenPositionsRule, RiskAction,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def nifty_eq() -> Instrument:
    return Instrument(
        symbol="RELIANCE",
        trading_symbol="RELIANCE-EQ",
        token="2885",
        exchange=Exchange.NSE,
        instrument_type=InstrumentType.EQ,
        name="Reliance Industries Ltd",
        lot_size=1,
        tick_size=0.05,
    )


@pytest.fixture
def nifty_fut() -> Instrument:
    return Instrument(
        symbol="NIFTY",
        trading_symbol="NIFTY24JUNFUT",
        token="99926000",
        exchange=Exchange.NFO,
        instrument_type=InstrumentType.FUT,
        expiry=date(2024, 6, 27),
        lot_size=50,
        tick_size=0.05,
    )


@pytest.fixture
def nifty_ce() -> Instrument:
    return Instrument(
        symbol="NIFTY",
        trading_symbol="NIFTY24JUN23000CE",
        token="43521",
        exchange=Exchange.NFO,
        instrument_type=InstrumentType.CE,
        option_type=OptionType.CE,
        expiry=date(2024, 6, 27),
        strike=23000.0,
        lot_size=50,
        tick_size=0.05,
    )


@pytest.fixture
def sample_candle() -> Candle:
    return Candle(
        timestamp=datetime(2024, 1, 15, 9, 15),
        open=450.0,
        high=460.0,
        low=445.0,
        close=455.0,
        volume=100000,
        symbol="RELIANCE",
        interval="1d",
    )


@pytest.fixture
def sample_portfolio() -> Portfolio:
    return Portfolio(name="Test Portfolio", initial_capital=1_000_000.0)


# ============================================================
# INSTRUMENT TESTS
# ============================================================

class TestInstrument:
    def test_equity_creation(self, nifty_eq):
        assert nifty_eq.symbol == "RELIANCE"
        assert nifty_eq.instrument_type == InstrumentType.EQ
        assert nifty_eq.is_equity
        assert not nifty_eq.is_derivative
        assert not nifty_eq.is_option

    def test_futures_creation(self, nifty_fut):
        assert nifty_fut.instrument_type == InstrumentType.FUT
        assert nifty_fut.is_derivative
        assert nifty_fut.lot_size == 50
        assert nifty_fut.expiry == date(2024, 6, 27)

    def test_option_creation(self, nifty_ce):
        assert nifty_ce.instrument_type == InstrumentType.CE
        assert nifty_ce.is_option
        assert nifty_ce.strike == 23000.0
        assert nifty_ce.option_type == OptionType.CE

    def test_futures_requires_expiry(self):
        with pytest.raises(ValueError, match="expiry"):
            Instrument(
                symbol="NIFTY",
                trading_symbol="NIFTYFUT",
                token="1",
                exchange=Exchange.NFO,
                instrument_type=InstrumentType.FUT,
            )

    def test_option_requires_strike(self):
        with pytest.raises(ValueError, match="strike"):
            Instrument(
                symbol="NIFTY",
                trading_symbol="NIFTYCE",
                token="2",
                exchange=Exchange.NFO,
                instrument_type=InstrumentType.CE,
                option_type=OptionType.CE,
                expiry=date(2024, 6, 27),
            )

    def test_contract_value(self, nifty_fut):
        value = nifty_fut.contract_value(22000.0)
        assert value == 22000.0 * 50  # lot_size=50

    def test_symbol_uppercased(self):
        inst = Instrument(
            symbol="reliance",
            trading_symbol="reliance-eq",
            token="2885",
            exchange=Exchange.NSE,
            instrument_type=InstrumentType.EQ,
        )
        assert inst.symbol == "RELIANCE"
        assert inst.trading_symbol == "RELIANCE-EQ"


# ============================================================
# CANDLE TESTS
# ============================================================

class TestCandle:
    def test_valid_candle(self, sample_candle):
        assert sample_candle.is_bullish
        assert not sample_candle.is_bearish
        assert sample_candle.range == 15.0  # 460-445
        assert sample_candle.body == 5.0    # 455-450

    def test_high_lt_low_raises(self):
        with pytest.raises(ValueError, match="high"):
            Candle(
                timestamp=datetime.utcnow(),
                open=100, high=90, low=95, close=97
            )

    def test_high_lt_close_raises(self):
        with pytest.raises(ValueError, match="high"):
            Candle(
                timestamp=datetime.utcnow(),
                open=100, high=95, low=90, close=97
            )

    def test_typical_price(self, sample_candle):
        expected = (460 + 445 + 455) / 3
        assert abs(sample_candle.typical_price - expected) < 0.001

    def test_change_pct(self, sample_candle):
        expected = ((455 - 450) / 450) * 100
        assert abs(sample_candle.change_pct - expected) < 0.001

    def test_doji_detection(self):
        doji = Candle(
            timestamp=datetime.utcnow(),
            open=100, high=105, low=95, close=100.1
        )
        assert doji.is_doji


# ============================================================
# ORDER TESTS
# ============================================================

class TestOrder:
    def test_market_order_creation(self):
        order = Order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == 0
        assert order.pending_quantity == 10

    def test_limit_order_requires_price(self):
        with pytest.raises(ValueError, match="price"):
            Order(
                symbol="RELIANCE",
                exchange=Exchange.NSE,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
            )

    def test_stop_order_requires_stop_price(self):
        with pytest.raises(ValueError, match="stop_price"):
            Order(
                symbol="RELIANCE",
                exchange=Exchange.NSE,
                side=OrderSide.BUY,
                order_type=OrderType.STOP,
                quantity=10,
            )

    def test_full_fill(self):
        order = Order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        order.transition(OrderStatus.OPEN)
        order.fill(10, 450.0)
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 10
        assert order.average_price == 450.0
        assert order.pending_quantity == 0

    def test_partial_fill(self):
        order = Order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        order.transition(OrderStatus.OPEN)
        order.fill(5, 450.0)
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == 5
        assert order.pending_quantity == 5

    def test_weighted_average_price(self):
        order = Order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        order.transition(OrderStatus.OPEN)
        order.fill(5, 400.0)
        order.fill(5, 500.0)
        assert order.average_price == 450.0

    def test_invalid_transition_raises(self):
        order = Order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        with pytest.raises(ValueError, match="Invalid transition"):
            order.transition(OrderStatus.FILLED)  # PENDING → FILLED is not allowed

    def test_terminal_status(self):
        order = Order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        order.transition(OrderStatus.OPEN)
        order.fill(10, 450.0)
        assert order.is_terminal


# ============================================================
# TRADE PnL TESTS
# ============================================================

class TestTrade:
    def test_long_winner(self):
        trade = Trade(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
            quantity=10,
            entry_price=400.0,
            exit_price=450.0,
            entry_time=datetime(2024, 1, 1),
            exit_time=datetime(2024, 1, 10),
            commission=100.0,
        )
        assert trade.gross_pnl == 500.0  # (450-400)*10
        assert trade.net_pnl == 400.0   # 500-100
        assert trade.is_winner
        assert not trade.is_loser

    def test_long_loser(self):
        trade = Trade(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
            quantity=10,
            entry_price=450.0,
            exit_price=400.0,
            entry_time=datetime(2024, 1, 1),
            exit_time=datetime(2024, 1, 10),
        )
        assert trade.gross_pnl == -500.0
        assert trade.is_loser

    def test_short_winner(self):
        trade = Trade(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.SHORT,
            quantity=10,
            entry_price=450.0,
            exit_price=400.0,
            entry_time=datetime(2024, 1, 1),
            exit_time=datetime(2024, 1, 10),
        )
        assert trade.gross_pnl == 500.0  # short wins when price drops
        assert trade.is_winner

    def test_exit_before_entry_raises(self):
        with pytest.raises(ValueError, match="exit_time"):
            Trade(
                symbol="RELIANCE",
                exchange=Exchange.NSE,
                side=PositionSide.LONG,
                quantity=10,
                entry_price=400.0,
                exit_price=450.0,
                entry_time=datetime(2024, 1, 10),
                exit_time=datetime(2024, 1, 1),  # before entry!
            )

    def test_return_pct(self):
        trade = Trade(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
            quantity=10,
            entry_price=400.0,
            exit_price=440.0,
            entry_time=datetime(2024, 1, 1),
            exit_time=datetime(2024, 1, 10),
        )
        assert abs(trade.return_pct - 10.0) < 0.001  # 10% return


# ============================================================
# POSITION TESTS
# ============================================================

class TestPosition:
    def test_position_lifecycle(self):
        pos = Position(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
        )
        pos.add_fill(10, 400.0, commission=50.0)
        assert pos.quantity == 10
        assert pos.average_entry_price == 400.0
        assert pos.exposure == 4000.0

    def test_unrealized_pnl_long(self):
        pos = Position(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
        )
        pos.add_fill(10, 400.0)
        pos.update_last_price(450.0)
        assert pos.unrealized_pnl == 500.0  # (450-400)*10

    def test_unrealized_pnl_short(self):
        pos = Position(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.SHORT,
        )
        pos.add_fill(10, 450.0)
        pos.update_last_price(400.0)
        assert pos.unrealized_pnl == 500.0  # (450-400)*10 short wins on drop

    def test_close_produces_trade(self):
        pos = Position(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
        )
        pos.add_fill(10, 400.0)
        trade = pos.close(exit_price=450.0, commission=100.0)
        assert isinstance(trade, Trade)
        assert trade.net_pnl == 400.0  # (450-400)*10 - 100 commission
        assert pos.quantity == 0
        assert not pos.is_open

    def test_partial_close(self):
        pos = Position(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
        )
        pos.add_fill(10, 400.0)
        trade = pos.close_partial(close_qty=5, exit_price=450.0)
        assert pos.quantity == 5
        assert pos.is_open
        assert trade.net_pnl == 250.0  # (450-400)*5

    def test_weighted_average_entry(self):
        pos = Position(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
        )
        pos.add_fill(5, 400.0)
        pos.add_fill(5, 500.0)
        assert pos.average_entry_price == 450.0

    def test_close_more_than_held_raises(self):
        pos = Position(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
        )
        pos.add_fill(5, 400.0)
        with pytest.raises(ValueError, match="Cannot close"):
            pos.close_partial(close_qty=10, exit_price=450.0)


# ============================================================
# PORTFOLIO TESTS
# ============================================================

class TestPortfolio:
    def test_initial_state(self, sample_portfolio):
        assert sample_portfolio.cash == 1_000_000.0
        assert sample_portfolio.equity == 1_000_000.0
        assert sample_portfolio.total_return_pct == 0.0

    def test_add_and_close_position(self, sample_portfolio):
        pos = Position(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=PositionSide.LONG,
        )
        pos.add_fill(10, 400.0)
        sample_portfolio.add_position(pos)
        assert "RELIANCE" in sample_portfolio.open_positions
        assert sample_portfolio.cash == 1_000_000.0 - 4_000.0

        trade = sample_portfolio.close_position("RELIANCE", exit_price=450.0)
        assert trade is not None
        assert trade.net_pnl == 500.0
        assert "RELIANCE" not in sample_portfolio.open_positions
        assert len(sample_portfolio.closed_trades) == 1

    def test_win_rate(self, sample_portfolio):
        for entry, exit_ in [(400, 450), (500, 550), (300, 280)]:
            trade = Trade(
                symbol="X", exchange=Exchange.NSE,
                side=PositionSide.LONG, quantity=1,
                entry_price=float(entry), exit_price=float(exit_),
                entry_time=datetime(2024, 1, 1),
                exit_time=datetime(2024, 1, 2),
            )
            sample_portfolio.closed_trades.append(trade)
        assert abs(sample_portfolio.win_rate - 66.67) < 0.1

    def test_profit_factor(self, sample_portfolio):
        trades = [
            Trade(symbol="X", exchange=Exchange.NSE, side=PositionSide.LONG,
                  quantity=1, entry_price=100.0, exit_price=200.0,
                  entry_time=datetime(2024, 1, 1), exit_time=datetime(2024, 1, 2)),
            Trade(symbol="X", exchange=Exchange.NSE, side=PositionSide.LONG,
                  quantity=1, entry_price=200.0, exit_price=150.0,
                  entry_time=datetime(2024, 1, 3), exit_time=datetime(2024, 1, 4)),
        ]
        sample_portfolio.closed_trades.extend(trades)
        assert sample_portfolio.profit_factor == 2.0  # 100 profit / 50 loss


# ============================================================
# BACKTEST RESULT TESTS
# ============================================================

class TestBacktestResult:
    def test_metrics_computation(self):
        result = BacktestResult(
            strategy_name="TestStrategy",
            symbol="NIFTY",
            exchange="NFO",
            timeframe="1d",
            from_date=datetime(2023, 1, 1),
            to_date=datetime(2023, 12, 31),
            initial_capital=1_000_000.0,
            equity_curve=[1_000_000, 1_050_000, 1_020_000, 1_100_000, 1_080_000],
        )
        trades = [
            Trade(symbol="NIFTY", exchange=Exchange.NSE, side=PositionSide.LONG,
                  quantity=50, entry_price=18000.0, exit_price=18500.0,
                  entry_time=datetime(2023, 1, 10), exit_time=datetime(2023, 1, 20)),
            Trade(symbol="NIFTY", exchange=Exchange.NSE, side=PositionSide.LONG,
                  quantity=50, entry_price=19000.0, exit_price=18800.0,
                  entry_time=datetime(2023, 2, 1), exit_time=datetime(2023, 2, 10)),
        ]
        result.trade_log = trades
        result.compute_metrics()
        assert result.total_trades == 2
        assert result.winning_trades == 1
        assert result.losing_trades == 1
        assert result.win_rate == 50.0
        assert result.max_drawdown_pct > 0


# ============================================================
# RISK RULE TESTS
# ============================================================

class TestRiskRules:
    def test_max_order_size_blocked(self, sample_portfolio):
        rule = MaxOrderSizeRule(
            rule_id="r1",
            name="MaxOrderSize",
            action=RiskAction.BLOCK,
            parameters={"max_order_value": 1000.0},  # very small limit
        )
        order = Order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=500.0,  # 50,000 — exceeds 1000
        )
        result = rule.evaluate(order, sample_portfolio)
        assert result.triggered
        assert result.action == RiskAction.BLOCK

    def test_max_order_size_allowed(self, sample_portfolio):
        rule = MaxOrderSizeRule(
            rule_id="r1",
            name="MaxOrderSize",
            action=RiskAction.BLOCK,
            parameters={"max_order_value": 100_000.0},
        )
        order = Order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=500.0,  # 5,000 — within limit
        )
        result = rule.evaluate(order, sample_portfolio)
        assert not result.triggered

    def test_ruleset_default_blocks_oversized_order(self, sample_portfolio):
        ruleset = RiskRuleSet.default(initial_capital=1_000_000.0)
        order = Order(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1000,
            price=1000.0,  # 1,000,000 — way over 5% = 50,000 limit
        )
        approved, results = ruleset.evaluate(order, sample_portfolio)
        assert not approved
        blocked = [r for r in results if r.action == RiskAction.BLOCK and r.triggered]
        assert len(blocked) >= 1
