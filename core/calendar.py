"""NSE Market Calendar — trading days, session times, and holiday awareness.

Provides helpers consumed by strategies, the scheduler, and the data layer
to decide whether the market is open and where session boundaries fall.

All times are in IST (Asia/Kolkata, UTC+5:30).
Session: 09:15 – 15:30  Monday–Friday, excluding NSE holidays.

Holiday list covers NSE 2025–2026.  Update `_NSE_HOLIDAYS` each year.

Usage:
    from core.calendar import MarketCalendar

    cal = MarketCalendar()
    if cal.is_market_open():
        ...
    today_open = cal.is_trading_day()
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# NSE declared holidays — update each year
_NSE_HOLIDAYS: frozenset[date] = frozenset({
    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramadan Eid)
    date(2025, 4, 10),   # Shri Ram Navami
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti / Mahatma Gandhi
    date(2025, 10, 2),   # Dussehra (same day)
    date(2025, 10, 24),  # Diwali Laxmi Pujan
    date(2025, 10, 25),  # Diwali Balipratipada
    date(2025, 11, 5),   # Prakash Gurpurb Sri Guru Nanak Dev Ji
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 20),   # Holi
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 4, 15),   # Ram Navami
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 11, 14),  # Diwali Laxmi Pujan (tentative)
    date(2026, 12, 25),  # Christmas
})

_SESSION_START = time(9, 15)
_SESSION_END   = time(15, 30)
_PRE_OPEN_END  = time(9, 15)  # pre-open closes at session start


class MarketCalendar:
    """NSE market calendar with session and holiday awareness."""

    def now_ist(self) -> datetime:
        """Current datetime in IST."""
        return datetime.now(tz=IST)

    def today(self) -> date:
        return self.now_ist().date()

    def is_trading_day(self, d: date | None = None) -> bool:
        """Return True if `d` (default today) is an NSE trading day."""
        d = d or self.today()
        if d.weekday() >= 5:        # Saturday=5, Sunday=6
            return False
        return d not in _NSE_HOLIDAYS

    def is_market_open(self, dt: datetime | None = None) -> bool:
        """Return True if the market is currently in its continuous session."""
        dt = dt or self.now_ist()
        if not self.is_trading_day(dt.date()):
            return False
        t = dt.time()
        return _SESSION_START <= t <= _SESSION_END

    def session_start(self, d: date | None = None) -> datetime:
        """Return session start datetime (09:15 IST) for trading day `d`."""
        d = d or self.today()
        return datetime.combine(d, _SESSION_START, tzinfo=IST)

    def session_end(self, d: date | None = None) -> datetime:
        """Return session end datetime (15:30 IST) for trading day `d`."""
        d = d or self.today()
        return datetime.combine(d, _SESSION_END, tzinfo=IST)

    def minutes_to_open(self) -> int:
        """Minutes until next session open.  0 if market is already open."""
        now = self.now_ist()
        if self.is_market_open(now):
            return 0
        # find next trading day
        d = now.date()
        for _ in range(10):
            if self.is_trading_day(d):
                open_dt = self.session_start(d)
                if open_dt > now:
                    delta = open_dt - now
                    return int(delta.total_seconds() // 60)
            from datetime import timedelta
            d += timedelta(days=1)
        return -1

    def minutes_to_close(self) -> int:
        """Minutes until session close.  -1 if market is not open."""
        now = self.now_ist()
        if not self.is_market_open(now):
            return -1
        close_dt = self.session_end(now.date())
        delta = close_dt - now
        return int(delta.total_seconds() // 60)

    def is_last_30_minutes(self) -> bool:
        """True during the final 30 minutes of the session (15:00–15:30)."""
        now = self.now_ist()
        if not self.is_market_open(now):
            return False
        return self.minutes_to_close() <= 30


# Module-level singleton — import and use directly
calendar = MarketCalendar()
