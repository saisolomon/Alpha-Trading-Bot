"""
Prague-timezone utilities.

FTMO's accounting day resets at 00:00 Europe/Prague (CE(S)T).
This is UTC+1 in winter, UTC+2 in summer — distinct from broker server time,
which is often UTC+2/+3 year-round.  Every boundary check in the bot MUST use
these helpers, never bare datetime.now() or UTC arithmetic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PRAGUE_TZ = ZoneInfo("Europe/Prague")
UTC_TZ = timezone.utc


def prague_now() -> datetime:
    """Current wall-clock time expressed in the Europe/Prague timezone."""
    return datetime.now(tz=PRAGUE_TZ)


def to_prague(dt: datetime) -> datetime:
    """Convert any timezone-aware datetime to Europe/Prague."""
    if dt.tzinfo is None:
        raise ValueError(f"Naive datetime passed to to_prague(): {dt!r}")
    return dt.astimezone(PRAGUE_TZ)


def to_utc(dt: datetime) -> datetime:
    """Convert any timezone-aware datetime to UTC."""
    if dt.tzinfo is None:
        raise ValueError(f"Naive datetime passed to to_utc(): {dt!r}")
    return dt.astimezone(UTC_TZ)


def prague_midnight_of(dt: datetime) -> datetime:
    """Return 00:00:00 Europe/Prague on the same calendar day as dt.

    dt may be in any timezone; it is converted to Prague first.
    The returned datetime is timezone-aware (Europe/Prague).
    """
    prague = to_prague(dt)
    return prague.replace(hour=0, minute=0, second=0, microsecond=0)


def next_prague_midnight(dt: datetime) -> datetime:
    """Return the next 00:00:00 Europe/Prague strictly after dt.

    Used by the equity watcher to schedule the next daily-reset event.
    """
    today_midnight = prague_midnight_of(dt)
    prague = to_prague(dt)
    if prague >= today_midnight + timedelta(seconds=1):
        return today_midnight + timedelta(days=1)
    return today_midnight


def seconds_until_next_prague_midnight(dt: datetime | None = None) -> float:
    """Seconds from now (or from dt) until the next Prague-midnight boundary."""
    now = dt if dt is not None else prague_now()
    target = next_prague_midnight(now)
    delta = to_utc(target) - to_utc(now)
    return delta.total_seconds()


def is_same_prague_day(a: datetime, b: datetime) -> bool:
    """True if a and b fall on the same calendar day in Europe/Prague."""
    return prague_midnight_of(a) == prague_midnight_of(b)


def utc_now() -> datetime:
    """Current UTC time (timezone-aware)."""
    return datetime.now(tz=UTC_TZ)
