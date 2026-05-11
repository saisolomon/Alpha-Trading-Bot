"""
Unit tests for risk/news_blackout.py.

Covers: CSV/JSON loading, is_blackout logic, account-type filtering,
symbol-to-currency resolution, next_clear_time, and hot-reload.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from risk.ftmo import FTMOAccountType
from risk.news_blackout import (
    NewsBlackoutGate,
    NewsCalendar,
    NewsEvent,
)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NFP_TIME = datetime(2026, 5, 1, 13, 30, 0, tzinfo=UTC)


def _event(
    event_time: datetime = NFP_TIME,
    currency: str = "USD",
    title: str = "NFP",
    impact: str = "high",
) -> NewsEvent:
    return NewsEvent(event_time=event_time, currency=currency, title=title, impact=impact)


def _calendar(*events: NewsEvent) -> NewsCalendar:
    return NewsCalendar(list(events))


def _gate(window_minutes: int = 2, *events: NewsEvent) -> NewsBlackoutGate:
    return NewsBlackoutGate(_calendar(*events), window_minutes=window_minutes)


def _write_csv(path: Path, rows: list[dict]) -> None:
    import csv
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["datetime_utc", "currency", "title", "impact"])
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# NewsEvent helpers
# ---------------------------------------------------------------------------


def test_news_event_is_high_impact() -> None:
    e = _event(impact="high")
    assert e.is_high_impact() is True


def test_news_event_not_high_impact_on_medium() -> None:
    e = _event(impact="medium")
    assert e.is_high_impact() is False


# ---------------------------------------------------------------------------
# NewsCalendar.from_csv
# ---------------------------------------------------------------------------


def test_from_csv_loads_events(tmp_path: Path) -> None:
    csv_path = tmp_path / "cal.csv"
    _write_csv(csv_path, [
        {"datetime_utc": "2026-05-01T13:30:00+00:00", "currency": "USD", "title": "NFP", "impact": "high"},
        {"datetime_utc": "2026-05-01T14:00:00+00:00", "currency": "EUR", "title": "ECB", "impact": "high"},
    ])
    cal = NewsCalendar.from_csv(csv_path)
    assert len(cal) == 2


def test_from_csv_naive_datetime_assumed_utc(tmp_path: Path) -> None:
    csv_path = tmp_path / "cal.csv"
    _write_csv(csv_path, [
        {"datetime_utc": "2026-05-01T13:30:00", "currency": "USD", "title": "NFP", "impact": "high"},
    ])
    cal = NewsCalendar.from_csv(csv_path)
    events = cal.events_near(frozenset({"USD"}), NFP_TIME, 120)
    assert len(events) == 1


def test_from_csv_skips_bad_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "cal.csv"
    csv_path.write_text(
        "datetime_utc,currency,title,impact\n"
        "NOT_A_DATE,USD,NFP,high\n"
        "2026-05-01T13:30:00+00:00,USD,NFP,high\n",
        encoding="utf-8",
    )
    cal = NewsCalendar.from_csv(csv_path)
    assert len(cal) == 1


# ---------------------------------------------------------------------------
# NewsCalendar.from_json
# ---------------------------------------------------------------------------


def test_from_json_loads_events(tmp_path: Path) -> None:
    data = [
        {"datetime_utc": "2026-05-01T13:30:00+00:00", "currency": "USD", "title": "NFP", "impact": "high"},
        {"datetime_utc": "2026-05-01T18:00:00+00:00", "currency": "GBP", "title": "BOE", "impact": "high"},
    ]
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    cal = NewsCalendar.from_json(p)
    assert len(cal) == 2


def test_from_json_defaults_impact_to_high(tmp_path: Path) -> None:
    data = [{"datetime_utc": "2026-05-01T13:30:00+00:00", "currency": "USD", "title": "NFP"}]
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    cal = NewsCalendar.from_json(p)
    events = cal.events_near(frozenset({"USD"}), NFP_TIME, 60)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# NewsCalendar.events_near
# ---------------------------------------------------------------------------


def test_events_near_finds_event_at_exact_time() -> None:
    cal = _calendar(_event())
    events = cal.events_near(frozenset({"USD"}), NFP_TIME, 120)
    assert len(events) == 1


def test_events_near_finds_event_before_window() -> None:
    cal = _calendar(_event())
    query_time = NFP_TIME + timedelta(minutes=1, seconds=59)
    events = cal.events_near(frozenset({"USD"}), query_time, 120)
    assert len(events) == 1


def test_events_near_misses_event_outside_window() -> None:
    cal = _calendar(_event())
    query_time = NFP_TIME + timedelta(minutes=3)
    events = cal.events_near(frozenset({"USD"}), query_time, 120)
    assert len(events) == 0


def test_events_near_ignores_medium_impact() -> None:
    cal = _calendar(_event(impact="medium"))
    events = cal.events_near(frozenset({"USD"}), NFP_TIME, 120)
    assert len(events) == 0


def test_events_near_ignores_wrong_currency() -> None:
    cal = _calendar(_event(currency="EUR"))
    events = cal.events_near(frozenset({"USD"}), NFP_TIME, 120)
    assert len(events) == 0


def test_events_near_matches_either_currency() -> None:
    cal = _calendar(_event(currency="EUR"))
    events = cal.events_near(frozenset({"EUR", "USD"}), NFP_TIME, 120)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# NewsBlackoutGate.is_blackout
# ---------------------------------------------------------------------------


def test_is_blackout_true_at_event_time() -> None:
    gate = _gate(2, _event())
    assert gate.is_blackout("EURUSD", NFP_TIME) is True


def test_is_blackout_true_one_minute_before() -> None:
    gate = _gate(2, _event())
    assert gate.is_blackout("EURUSD", NFP_TIME - timedelta(minutes=1)) is True


def test_is_blackout_true_one_minute_after() -> None:
    gate = _gate(2, _event())
    assert gate.is_blackout("EURUSD", NFP_TIME + timedelta(minutes=1)) is True


def test_is_blackout_false_three_minutes_after() -> None:
    gate = _gate(2, _event())
    assert gate.is_blackout("EURUSD", NFP_TIME + timedelta(minutes=3)) is False


def test_is_blackout_false_unaffected_symbol() -> None:
    gate = _gate(2, _event(currency="JPY"))
    # EURUSD is only affected by EUR and USD, not JPY
    assert gate.is_blackout("EURUSD", NFP_TIME) is False


def test_is_blackout_false_for_non_news_account() -> None:
    gate = _gate(2, _event())
    # Account types without news restriction should return False immediately
    for t in FTMOAccountType:
        if not t.news_restriction_applies():
            assert gate.is_blackout("EURUSD", NFP_TIME, account_type=t) is False


def test_is_blackout_true_for_funded_standard() -> None:
    gate = _gate(2, _event())
    assert gate.is_blackout(
        "EURUSD", NFP_TIME, account_type=FTMOAccountType.FUNDED_STANDARD
    ) is True


def test_is_blackout_false_when_empty_calendar() -> None:
    gate = NewsBlackoutGate(NewsCalendar.empty(), window_minutes=2)
    assert gate.is_blackout("EURUSD", NFP_TIME) is False


# ---------------------------------------------------------------------------
# Symbol → currency resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol,expected", [
    ("EURUSD", frozenset({"EUR", "USD"})),
    ("GBPJPY", frozenset({"GBP", "JPY"})),
    ("XAUUSD", frozenset({"USD", "GOLD"})),
    ("US30", frozenset({"USD", "US"})),
    ("DE40", frozenset({"EUR", "DE"})),
])
def test_currencies_for_known_symbols(symbol: str, expected: frozenset) -> None:
    from risk.news_blackout import NewsBlackoutGate
    result = NewsBlackoutGate._currencies_for(symbol)
    assert result == expected


def test_currencies_for_broker_suffix_stripped() -> None:
    # EURUSD.r should resolve same as EURUSD
    result = NewsBlackoutGate._currencies_for("EURUSD.r")
    assert "EUR" in result
    assert "USD" in result


def test_currencies_for_unknown_6char_fallback() -> None:
    result = NewsBlackoutGate._currencies_for("ABCDEF")
    assert result == frozenset({"ABC", "DEF"})


def test_currencies_for_unknown_short_symbol_returns_empty() -> None:
    result = NewsBlackoutGate._currencies_for("XYZ")
    assert result == frozenset()


# ---------------------------------------------------------------------------
# next_clear_time
# ---------------------------------------------------------------------------


def test_next_clear_time_returns_none_when_no_events() -> None:
    gate = NewsBlackoutGate(NewsCalendar.empty(), window_minutes=2)
    assert gate.next_clear_time("EURUSD", NFP_TIME) is None


def test_next_clear_time_returns_end_of_window() -> None:
    gate = _gate(2, _event())
    clear = gate.next_clear_time("EURUSD", NFP_TIME)
    expected = NFP_TIME + timedelta(minutes=2)
    assert clear == expected


def test_next_clear_time_covers_multiple_events() -> None:
    e1 = _event(event_time=NFP_TIME, currency="USD")
    e2 = _event(event_time=NFP_TIME + timedelta(minutes=3), currency="USD")
    gate = _gate(2, e1, e2)
    clear = gate.next_clear_time("EURUSD", NFP_TIME)
    # Window ends at NFP_TIME+3min + 2min window = NFP_TIME + 5min
    expected = NFP_TIME + timedelta(minutes=5)
    assert clear == expected


def test_next_clear_time_returns_none_for_unaffected_symbol() -> None:
    gate = _gate(2, _event(currency="JPY"))
    assert gate.next_clear_time("EURUSD", NFP_TIME) is None


# ---------------------------------------------------------------------------
# Hot reload
# ---------------------------------------------------------------------------


def test_reload_csv(tmp_path: Path) -> None:
    gate = NewsBlackoutGate(NewsCalendar.empty(), window_minutes=2)
    assert gate.is_blackout("EURUSD", NFP_TIME) is False

    csv_path = tmp_path / "cal.csv"
    _write_csv(csv_path, [
        {"datetime_utc": NFP_TIME.isoformat(), "currency": "USD", "title": "NFP", "impact": "high"},
    ])
    gate.reload(csv_path)
    assert gate.is_blackout("EURUSD", NFP_TIME) is True


def test_reload_json(tmp_path: Path) -> None:
    gate = NewsBlackoutGate(NewsCalendar.empty(), window_minutes=2)
    data = [{"datetime_utc": NFP_TIME.isoformat(), "currency": "USD", "title": "NFP", "impact": "high"}]
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    gate.reload(p)
    assert gate.is_blackout("EURUSD", NFP_TIME) is True


def test_reload_unsupported_format_raises(tmp_path: Path) -> None:
    gate = NewsBlackoutGate(NewsCalendar.empty())
    bad_path = tmp_path / "cal.txt"
    bad_path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        gate.reload(bad_path)
