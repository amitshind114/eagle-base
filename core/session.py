"""Trading session lifecycle — start, run, and close a session cleanly.

Manages:
    - risk_limits reset at session open
    - audit SESSION_START / SESSION_END bookends
    - session report generation at close
    - scheduler integration (registers pre-market and post-market jobs)

Designed as a context manager for both paper and live modes:

    with TradingSession(broker, capital=200_000, mode="paper") as session:
        # market is open, risk limits are fresh, audit is running
        pass
    # session report is saved automatically on exit

Or use start() / close() explicitly in scheduler jobs:

    sched = Scheduler()

    @sched.at_time(9, 10)
    def pre_market():
        session.start()

    @sched.at_time(15, 25)
    def post_market():
        session.close()
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from core.audit import audit
from core.logger import logger
from risk.limits import risk_limits

IST = ZoneInfo("Asia/Kolkata")


class TradingSession:
    """Manages the full lifecycle of one trading session."""

    def __init__(
        self,
        broker: Any,                # PaperBroker or LiveExecutor
        capital: float,
        mode: str = "paper",        # "paper" | "live"
    ) -> None:
        self.broker  = broker
        self.capital = capital
        self.mode    = mode
        self._open   = False
        self._report_path = None

    # ── Context manager ───────────────────────────────────────────────────

    def __enter__(self) -> "TradingSession":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the session: reset risk limits, audit, log."""
        risk_limits.reset(capital=self.capital)
        audit.record("SESSION_START", "SYSTEM", session=self.mode,
                     capital=self.capital,
                     ts=datetime.now(tz=IST).isoformat(timespec="seconds"))
        self._open = True
        logger.info(
            f"[session] {self.mode.upper()} session started — "
            f"capital=₹{self.capital:,.0f} "
            f"limits={risk_limits.status()}"
        )

    def close(self) -> None:
        """Close the session: save report, audit SESSION_END."""
        if not self._open:
            return
        self._open = False

        # Build and save session report if the broker has a trade_log
        trade_log = getattr(self.broker, "trade_log", None)
        if trade_log is not None:
            try:
                from reporting.session_report import SessionReport
                report = SessionReport.build(
                    trade_log=trade_log,
                    session=self.mode,
                    capital=self.capital,
                )
                self._report_path = report.save()
                logger.info(
                    f"[session] Report saved → {self._report_path}\n"
                    f"  trades={report.trade_summary.get('total_trades', 0)} "
                    f"  net_pnl=₹{report.trade_summary.get('net_pnl', 0):+.2f} "
                    f"  charges=₹{report.trade_summary.get('total_charges', 0):,.2f}"
                )
            except Exception as exc:
                logger.warning(f"[session] Report generation failed: {exc}")

        audit.record(
            "SESSION_END", "SYSTEM", session=self.mode,
            report=str(self._report_path) if self._report_path else None,
            limits=risk_limits.status(),
        )
        logger.info(f"[session] {self.mode.upper()} session closed")

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def report_path(self):
        return self._report_path

    # ── Scheduler wiring ──────────────────────────────────────────────────

    def register_with_scheduler(self, sched) -> None:
        """Register pre-market start and post-market close with a Scheduler.

        Pre-market:  09:10 IST — resets risk limits, opens session
        Post-market: 15:25 IST — closes session, saves report

        Usage:
            sched   = Scheduler()
            session = TradingSession(broker, capital=200_000, mode="paper")
            session.register_with_scheduler(sched)
            sched.start()
        """
        @sched.at_time(9, 10)
        def pre_market_open():
            self.start()

        @sched.at_time(15, 25)
        def post_market_close():
            self.close()

        logger.info(
            "[session] Registered pre-market(09:10) and post-market(15:25) with scheduler"
        )
