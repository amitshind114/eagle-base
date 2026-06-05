"""Post-session report — single call to capture everything from a session.

Aggregates:
    - TradeLog summary  (PnL, win rate, charges)
    - risk.metrics      (Sharpe, Sortino, max drawdown)
    - risk_limits.status (daily state: trades placed, remaining cap)
    - audit.today       (count of events by type)

Writes a JSON file to ~/.eagle/sessions/YYYY-MM-DD_{session}.json
so the Streamlit UI can load any past session without re-running.

Usage:
    from reporting.session_report import SessionReport
    from paper.broker import PaperBroker

    broker = PaperBroker(capital=200_000)
    # ... trading happens ...
    report = SessionReport.build(broker.trade_log, session="paper")
    path   = report.save()
    print(report.as_dict())
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST              = ZoneInfo("Asia/Kolkata")
_SESSIONS_DIR    = Path.home() / ".eagle" / "sessions"


@dataclass
class SessionReport:
    session:        str
    date:           str
    generated_at:   str
    capital:        float
    trade_summary:  dict
    risk_metrics:   dict
    limits_status:  dict
    audit_summary:  dict
    equity_curve:   list[float] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        trade_log,                         # reporting.trade_log.TradeLog
        session: str = "paper",
        capital: float = 0.0,
        equity_curve: list[float] | None = None,
    ) -> "SessionReport":
        """Build a SessionReport from a completed TradeLog.

        trade_log:    TradeLog instance from the session
        session:      "paper" | "live" | "backtest"
        capital:      starting capital for the session
        equity_curve: optional list of equity values (one per trade)
        """
        from core.audit import audit
        from risk.limits import risk_limits
        from risk.metrics import compute_metrics

        trade_summary = trade_log.summary()
        pnl_series    = [e.net_pnl for e in trade_log]

        eq_curve = equity_curve or (
            [capital + sum(pnl_series[: i + 1]) for i in range(len(pnl_series))]
            if pnl_series and capital > 0 else []
        )

        risk_metrics = compute_metrics(
            pnl_series=pnl_series,
            equity_curve=eq_curve if eq_curve else None,
        ) if pnl_series else {"error": "no trades"}

        limits = risk_limits.status()

        today_events   = audit.today(session=session)
        audit_summary  = {
            "total_events":  len(today_events),
            "gate_blocks":   sum(1 for e in today_events if e.get("event") == "GATE_BLOCK"),
            "orders_filled": sum(1 for e in today_events if e.get("event") == "ORDER_FILLED"),
            "rejected":      sum(1 for e in today_events if e.get("event") == "ORDER_REJECTED"),
        }

        now = datetime.now(tz=IST)

        return cls(
            session=session,
            date=now.strftime("%Y-%m-%d"),
            generated_at=now.isoformat(timespec="seconds"),
            capital=capital,
            trade_summary=trade_summary,
            risk_metrics=risk_metrics,
            limits_status=limits,
            audit_summary=audit_summary,
            equity_curve=[round(v, 2) for v in eq_curve],
        )

    def save(self, directory: Path | None = None) -> Path:
        """Write report to JSON.  Returns the path written."""
        out_dir  = directory or _SESSIONS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self.date}_{self.session}.json"
        path     = out_dir / filename
        path.write_text(
            json.dumps(self.as_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: str | Path) -> "SessionReport":
        """Load a previously saved report from JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)

    @staticmethod
    def list_saved(directory: Path | None = None) -> list[Path]:
        """Return all saved session report paths, newest first."""
        d = directory or _SESSIONS_DIR
        if not d.exists():
            return []
        return sorted(d.glob("*.json"), reverse=True)
