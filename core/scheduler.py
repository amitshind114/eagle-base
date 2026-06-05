"""Lightweight in-process job scheduler for market-hours automation.

Uses APScheduler (BackgroundScheduler) — runs as a daemon thread inside
the app process.  No external broker, no Redis, no Celery required.

Designed for:
    - Pre-market watchlist scan     (09:10 IST)
    - Intraday signal refresh       (every N minutes during session)
    - Post-market report generation (15:35 IST)
    - Custom one-off or recurring jobs

Requires: apscheduler
    pip install apscheduler

Usage:
    from core.scheduler import Scheduler

    sched = Scheduler()

    @sched.every_n_minutes(5)
    def my_scan():
        ...

    sched.start()
    # app runs ...
    sched.stop()
"""

from __future__ import annotations

import logging
from typing import Callable

from core.calendar import calendar as market_cal
from core.logger import logger

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    _HAS_APScheduler = True
except ImportError:
    _HAS_APScheduler = False


class Scheduler:
    """In-process background scheduler with market-hours awareness."""

    def __init__(self, timezone: str = "Asia/Kolkata") -> None:
        if not _HAS_APScheduler:
            raise ImportError(
                "apscheduler is required.  Install with: pip install apscheduler"
            )
        self._tz   = timezone
        self._sched = BackgroundScheduler(timezone=timezone)
        # suppress APScheduler's verbose INFO logs
        logging.getLogger("apscheduler").setLevel(logging.WARNING)

    # ── Decorators / convenience registration ──────────────────────────────

    def every_n_minutes(
        self, minutes: int, market_hours_only: bool = True
    ) -> Callable:
        """Decorator — run `func` every `minutes` minutes.

        When market_hours_only=True the job silently skips execution
        outside NSE session hours without needing any if-guards in the job.
        """
        def decorator(func: Callable) -> Callable:
            def guarded(*args, **kwargs):
                if market_hours_only and not market_cal.is_market_open():
                    return
                func(*args, **kwargs)

            self._sched.add_job(
                guarded,
                trigger=IntervalTrigger(minutes=minutes),
                id=func.__name__,
                replace_existing=True,
            )
            logger.info(f"[scheduler] Registered '{func.__name__}' every {minutes}m")
            return func
        return decorator

    def at_time(
        self,
        hour: int,
        minute: int,
        trading_days_only: bool = True,
    ) -> Callable:
        """Decorator — run `func` at a fixed IST time each day.

        When trading_days_only=True the job skips weekends and NSE holidays.
        """
        def decorator(func: Callable) -> Callable:
            def guarded(*args, **kwargs):
                if trading_days_only and not market_cal.is_trading_day():
                    return
                func(*args, **kwargs)

            self._sched.add_job(
                guarded,
                trigger=CronTrigger(
                    hour=hour, minute=minute, timezone=self._tz
                ),
                id=func.__name__,
                replace_existing=True,
            )
            logger.info(
                f"[scheduler] Registered '{func.__name__}' at {hour:02d}:{minute:02d} IST"
            )
            return func
        return decorator

    def add_job(
        self,
        func: Callable,
        trigger,
        job_id: str | None = None,
        **kwargs,
    ) -> None:
        """Low-level job registration — pass any APScheduler trigger directly."""
        self._sched.add_job(
            func,
            trigger=trigger,
            id=job_id or func.__name__,
            replace_existing=True,
            **kwargs,
        )

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background scheduler thread."""
        if not self._sched.running:
            self._sched.start()
            logger.info("[scheduler] Started")

    def stop(self, wait: bool = False) -> None:
        """Gracefully stop the scheduler."""
        if self._sched.running:
            self._sched.shutdown(wait=wait)
            logger.info("[scheduler] Stopped")

    @property
    def running(self) -> bool:
        return self._sched.running

    def list_jobs(self) -> list[str]:
        """Return names of all registered jobs."""
        return [job.id for job in self._sched.get_jobs()]
