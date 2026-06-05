"""Trade log — structured per-trade record with NSE charge computation.

Each completed trade (entry + exit pair) is recorded as a TradeEntry.
Charges are calculated using the Zerodha/NSE fee structure by default and
can be overridden per broker.

The TradeLog collects entries, computes running PnL, and can export to
CSV or return a summary dict for the reporting dashboard.

Usage:
    from reporting.trade_log import TradeLog, TradeEntry

    log = TradeLog()
    entry = TradeEntry.from_fill(
        symbol="RELIANCE",
        exchange="NSE",
        side="BUY",
        quantity=10,
        entry_price=2800.0,
        exit_price=2850.0,
        product="MIS",
        strategy="ema_crossover",
    )
    log.add(entry)
    print(log.summary())
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Literal
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

Product  = Literal["MIS", "CNC", "NRML"]
Side     = Literal["BUY", "SELL"]
Exchange = Literal["NSE", "BSE", "NFO", "MCX"]


# ── NSE charge constants (Zerodha defaults) ───────────────────────────────────
_BROKERAGE_INTRADAY   = 20.0          # flat ₹20 per executed order
_BROKERAGE_DELIVERY   = 0.0           # free for CNC at Zerodha
_STT_INTRADAY_SELL    = 0.00025       # 0.025% on sell side only
_STT_DELIVERY         = 0.001         # 0.1% on both sides
_EXCHANGE_TXN         = 0.0000335     # NSE transaction charge
_GST_RATE             = 0.18          # 18% GST on brokerage + exchange charges
_SEBI_CHARGE          = 0.000001      # ₹10 per crore
_STAMP_DUTY_BUY       = 0.00003       # 0.003% on buy side


def _compute_charges(
    turnover: float,
    product: Product,
    side: Side,
) -> float:
    """Return total charges (INR) for a single leg of a trade."""
    brokerage = (
        _BROKERAGE_INTRADAY if product in ("MIS", "NRML") else _BROKERAGE_DELIVERY
    )
    stt = (
        turnover * _STT_INTRADAY_SELL if product == "MIS" and side == "SELL"
        else turnover * _STT_DELIVERY if product == "CNC"
        else 0.0
    )
    exchange = turnover * _EXCHANGE_TXN
    sebi     = turnover * _SEBI_CHARGE
    stamp    = turnover * _STAMP_DUTY_BUY if side == "BUY" else 0.0
    gst      = (brokerage + exchange) * _GST_RATE
    return round(brokerage + stt + exchange + sebi + stamp + gst, 2)


@dataclass
class TradeEntry:
    """A single completed round-trip trade."""

    symbol:       str
    exchange:     Exchange
    side:         Side           # direction of the ENTRY leg
    quantity:     int
    entry_price:  float
    exit_price:   float
    product:      Product
    strategy:     str
    entry_time:   datetime = field(default_factory=lambda: datetime.now(tz=IST))
    exit_time:    datetime = field(default_factory=lambda: datetime.now(tz=IST))
    tag:          str = ""

    # Computed on creation — do not set manually
    gross_pnl:    float = field(init=False)
    charges:      float = field(init=False)
    net_pnl:      float = field(init=False)
    entry_value:  float = field(init=False)
    exit_value:   float = field(init=False)

    def __post_init__(self) -> None:
        self.entry_value = round(self.entry_price * self.quantity, 2)
        self.exit_value  = round(self.exit_price  * self.quantity, 2)
        direction        = 1 if self.side == "BUY" else -1
        self.gross_pnl   = round((self.exit_price - self.entry_price) * self.quantity * direction, 2)
        entry_charges    = _compute_charges(self.entry_value, self.product, self.side)
        exit_side: Side  = "SELL" if self.side == "BUY" else "BUY"
        exit_charges     = _compute_charges(self.exit_value,  self.product, exit_side)
        self.charges     = round(entry_charges + exit_charges, 2)
        self.net_pnl     = round(self.gross_pnl - self.charges, 2)

    @classmethod
    def from_fill(
        cls,
        symbol: str,
        exchange: Exchange,
        side: Side,
        quantity: int,
        entry_price: float,
        exit_price: float,
        product: Product = "MIS",
        strategy: str = "",
        tag: str = "",
    ) -> "TradeEntry":
        return cls(
            symbol=symbol,
            exchange=exchange,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            exit_price=exit_price,
            product=product,
            strategy=strategy,
            tag=tag,
        )

    def to_dict(self) -> dict:
        return {
            "symbol":      self.symbol,
            "exchange":    self.exchange,
            "side":        self.side,
            "quantity":    self.quantity,
            "entry_price": self.entry_price,
            "exit_price":  self.exit_price,
            "entry_value": self.entry_value,
            "exit_value":  self.exit_value,
            "gross_pnl":   self.gross_pnl,
            "charges":     self.charges,
            "net_pnl":     self.net_pnl,
            "product":     self.product,
            "strategy":    self.strategy,
            "entry_time":  self.entry_time.isoformat(),
            "exit_time":   self.exit_time.isoformat(),
            "tag":         self.tag,
        }


class TradeLog:
    """In-memory trade ledger with export and summary capabilities."""

    def __init__(self) -> None:
        self._entries: List[TradeEntry] = []

    def add(self, entry: TradeEntry) -> None:
        self._entries.append(entry)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    @property
    def entries(self) -> List[TradeEntry]:
        return list(self._entries)

    def summary(self) -> dict:
        """Return aggregate PnL statistics across all trades."""
        if not self._entries:
            return {"total_trades": 0, "net_pnl": 0.0, "gross_pnl": 0.0, "charges": 0.0}

        winners = [e for e in self._entries if e.net_pnl > 0]
        losers  = [e for e in self._entries if e.net_pnl <= 0]
        net_pnl = sum(e.net_pnl   for e in self._entries)
        gross   = sum(e.gross_pnl for e in self._entries)
        charges = sum(e.charges   for e in self._entries)

        return {
            "total_trades":   len(self._entries),
            "winners":        len(winners),
            "losers":         len(losers),
            "win_rate":       round(len(winners) / len(self._entries) * 100, 2),
            "gross_pnl":      round(gross, 2),
            "total_charges":  round(charges, 2),
            "net_pnl":        round(net_pnl, 2),
            "avg_net_pnl":    round(net_pnl / len(self._entries), 2),
            "best_trade":     round(max(e.net_pnl for e in self._entries), 2),
            "worst_trade":    round(min(e.net_pnl for e in self._entries), 2),
        }

    def to_csv(self, path: str | Path) -> Path:
        """Write all trade entries to a CSV file.  Returns the Path written."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self._entries:
            return path
        fieldnames = list(self._entries[0].to_dict().keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(e.to_dict() for e in self._entries)
        return path
