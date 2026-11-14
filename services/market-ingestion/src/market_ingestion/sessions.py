"""Trading-session helpers (IST), ported from vinzo-core daily.py."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def last_complete_session(now: datetime, close_hour_ist: int = 16) -> date:
    """Latest date whose daily bar is final. Before ~16:00 IST today's bar is still forming."""
    now_ist = now.astimezone(IST)
    d = now_ist.date()
    if now_ist.hour < close_hour_ist:
        d -= timedelta(days=1)
    return d


def prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def expected_latest_session(now: datetime, ready_hour_ist: int = 18) -> date:
    """Most recent weekday whose EOD bars should be available by now (IST)."""
    now_ist = now.astimezone(IST)
    d = now_ist.date()
    if d.weekday() >= 5 or now_ist.hour < ready_hour_ist:
        d = prev_weekday(d)
    return d
