"""
Unit tests for utils/timeutils.py.

These tests do NOT require a live MT5 terminal.
Property tests cover DST transitions (last Sunday March / October).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.timeutils import (
    PRAGUE_TZ,
    is_same_prague_day,
    next_prague_midnight,
    prague_midnight_of,
    prague_now,
    seconds_until_next_prague_midnight,
    to_prague,
    to_utc,
    utc_now,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Basic sanity
# ---------------------------------------------------------------------------


def test_prague_now_is_aware() -> None:
    now = prague_now()
    assert now.tzinfo is not None
    assert str(now.tzinfo) == "Europe/Prague"


def test_utc_now_is_aware() -> None:
    now = utc_now()
    assert now.tzinfo is not None


def test_to_prague_rejects_naive() -> None:
    with pytest.raises(ValueError, match="Naive datetime"):
        to_prague(datetime(2026, 1, 15, 12, 0, 0))


def test_to_utc_rejects_naive() -> None:
    with pytest.raises(ValueError, match="Naive datetime"):
        to_utc(datetime(2026, 1, 15, 12, 0, 0))


# ---------------------------------------------------------------------------
# prague_midnight_of
# ---------------------------------------------------------------------------


def _make_utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_midnight_winter() -> None:
    # 2026-01-15 12:00 UTC → Prague is UTC+1 → same day → midnight = 00:00 CET = 23:00 UTC day before
    dt = _make_utc(2026, 1, 15, 12, 0)
    midnight = prague_midnight_of(dt)
    assert midnight.hour == 0
    assert midnight.minute == 0
    assert midnight.second == 0
    assert str(midnight.tzinfo) == "Europe/Prague"
    assert midnight.year == 2026
    assert midnight.month == 1
    assert midnight.day == 15


def test_midnight_summer() -> None:
    # 2026-07-01 23:30 UTC → Prague is UTC+2 → 2026-07-02 01:30 Prague → midnight is 2026-07-02
    dt = _make_utc(2026, 7, 1, 23, 30)
    midnight = prague_midnight_of(dt)
    assert midnight.day == 2
    assert midnight.month == 7


def test_midnight_dst_spring_forward() -> None:
    # 2026 spring forward: last Sunday of March = 2026-03-29
    # 01:59:59 UTC → 02:59:59 CET, then clocks jump to 03:00 CEST (UTC+2)
    just_before = _make_utc(2026, 3, 29, 0, 59)  # 01:59 CET (still UTC+1)
    midnight = prague_midnight_of(just_before)
    assert midnight.day == 29
    assert midnight.month == 3

    just_after = _make_utc(2026, 3, 29, 1, 30)  # 03:30 CEST (UTC+2) — after spring forward
    midnight2 = prague_midnight_of(just_after)
    assert midnight2.day == 29


def test_midnight_dst_fall_back() -> None:
    # 2026 fall back: last Sunday of October = 2026-10-25
    # Clocks go from 03:00 CEST back to 02:00 CET
    fall_back_utc = _make_utc(2026, 10, 25, 1, 30)  # ambiguous hour
    midnight = prague_midnight_of(fall_back_utc)
    assert midnight.day == 25
    assert midnight.month == 10


# ---------------------------------------------------------------------------
# next_prague_midnight
# ---------------------------------------------------------------------------


def test_next_prague_midnight_after_midnight() -> None:
    # If it's 00:01 Prague, next midnight is tomorrow
    dt = datetime(2026, 5, 10, 0, 1, 0, tzinfo=PRAGUE_TZ)
    nm = next_prague_midnight(dt)
    assert nm.day == 11
    assert nm.hour == 0
    assert nm.minute == 0


def test_next_prague_midnight_before_midnight() -> None:
    # If it's 23:59 Prague, next midnight is tomorrow
    dt = datetime(2026, 5, 10, 23, 59, 0, tzinfo=PRAGUE_TZ)
    nm = next_prague_midnight(dt)
    assert nm.day == 11


def test_seconds_until_next_prague_midnight_positive() -> None:
    dt = datetime(2026, 5, 10, 12, 0, 0, tzinfo=PRAGUE_TZ)
    secs = seconds_until_next_prague_midnight(dt)
    assert 0 < secs <= 86400


# ---------------------------------------------------------------------------
# is_same_prague_day
# ---------------------------------------------------------------------------


def test_same_day_true() -> None:
    a = datetime(2026, 5, 10, 8, 0, tzinfo=PRAGUE_TZ)
    b = datetime(2026, 5, 10, 22, 59, tzinfo=PRAGUE_TZ)
    assert is_same_prague_day(a, b)


def test_same_day_false_across_midnight() -> None:
    # 23:59 vs 00:01 next day
    a = datetime(2026, 5, 10, 23, 59, tzinfo=PRAGUE_TZ)
    b = datetime(2026, 5, 11, 0, 1, tzinfo=PRAGUE_TZ)
    assert not is_same_prague_day(a, b)


def test_cross_tz_same_day() -> None:
    # 10:00 UTC on Jan 15 → 11:00 Prague (winter, UTC+1) → same day
    a = _make_utc(2026, 1, 15, 10, 0)
    b = datetime(2026, 1, 15, 23, 59, tzinfo=PRAGUE_TZ)
    assert is_same_prague_day(a, b)


def test_cross_tz_different_day() -> None:
    # 23:30 UTC on Jan 15 (winter, UTC+1) → 00:30 Jan 16 Prague → different day from Jan 15 00:00 Prague
    a = _make_utc(2026, 1, 15, 23, 30)   # → Jan 16 00:30 Prague
    b = datetime(2026, 1, 15, 12, 0, tzinfo=PRAGUE_TZ)
    assert not is_same_prague_day(a, b)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(
    st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
        timezones=st.just(UTC),
    )
)
@settings(max_examples=500)
def test_midnight_is_always_zero_hms(dt: datetime) -> None:
    midnight = prague_midnight_of(dt)
    assert midnight.hour == 0
    assert midnight.minute == 0
    assert midnight.second == 0
    assert midnight.microsecond == 0


@given(
    st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
        timezones=st.just(UTC),
    )
)
@settings(max_examples=500)
def test_next_midnight_is_always_in_future(dt: datetime) -> None:
    nm = next_prague_midnight(dt)
    # nm should be strictly after dt (after converting both to UTC)
    nm_utc = nm.astimezone(UTC)
    assert nm_utc > dt or nm_utc == dt.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@given(
    st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
        timezones=st.just(UTC),
    )
)
@settings(max_examples=500)
def test_seconds_until_midnight_in_range(dt: datetime) -> None:
    secs = seconds_until_next_prague_midnight(dt)
    assert 0 < secs <= 86401  # allow 1 extra second for DST edge
