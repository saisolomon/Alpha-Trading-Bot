"""
News Blackout Gate — blocks orders within ±N minutes of high-impact events.

Rule: On FUNDED_STANDARD accounts only, no opening or closing positions
within 2 minutes before/after any high-impact news release that affects
the traded symbol's currencies or markets.

Calendar sources (in preference order):
  1. Local CSV/JSON file (pre-downloaded, most reliable in production)
  2. ForexFactory weekly export (scrape-based, free)

Usage:
    calendar = NewsCalendar.from_csv("configs/news_calendar.csv")
    gate = NewsBlackoutGate(calendar, window_minutes=2)
    gate.is_blackout("EURUSD", datetime.now(UTC))   # True/False
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from risk.ftmo import FTMOAccountType
from utils.timeutils import utc_now

log = logging.getLogger(__name__)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Symbol → affected currencies/markets mapping
# ---------------------------------------------------------------------------

# Maps a canonical symbol base to the set of currency/market codes that a
# high-impact event on those codes would affect it.
_SYMBOL_CURRENCIES: dict[str, frozenset[str]] = {
    "EURUSD": frozenset({"EUR", "USD"}),
    "GBPUSD": frozenset({"GBP", "USD"}),
    "USDJPY": frozenset({"USD", "JPY"}),
    "USDCHF": frozenset({"USD", "CHF"}),
    "AUDUSD": frozenset({"AUD", "USD"}),
    "USDCAD": frozenset({"USD", "CAD"}),
    "NZDUSD": frozenset({"NZD", "USD"}),
    "EURGBP": frozenset({"EUR", "GBP"}),
    "EURJPY": frozenset({"EUR", "JPY"}),
    "GBPJPY": frozenset({"GBP", "JPY"}),
    "XAUUSD": frozenset({"USD", "GOLD"}),
    "US30":   frozenset({"USD", "US"}),
    "US500":  frozenset({"USD", "US"}),
    "US100":  frozenset({"USD", "US"}),
    "DE40":   frozenset({"EUR", "DE"}),
    "UK100":  frozenset({"GBP", "UK"}),
}

# High-impact event keywords → which currency/market codes they affect
_EVENT_CURRENCIES: dict[str, str] = {
    "NFP": "USD",
    "Non-Farm": "USD",
    "FOMC": "USD",
    "Federal Reserve": "USD",
    "Fed ": "USD",
    "CPI": "USD",          # default USD; override per event if needed
    "PPI": "USD",
    "GDP": "USD",
    "ECB": "EUR",
    "BOE": "GBP",
    "BOJ": "JPY",
    "RBA": "AUD",
    "BOC": "CAD",
    "RBNZ": "NZD",
    "SNB": "CHF",
}


@dataclass(frozen=True)
class NewsEvent:
    """A single high-impact economic event."""

    event_time: datetime     # UTC, timezone-aware
    currency: str            # e.g. "USD", "EUR"
    title: str
    impact: str              # "high", "medium", "low"

    def is_high_impact(self) -> bool:
        return self.impact.lower() == "high"


class NewsCalendar:
    """Container for a loaded set of NewsEvents."""

    def __init__(self, events: list[NewsEvent]) -> None:
        self._events = sorted(events, key=lambda e: e.event_time)

    @classmethod
    def empty(cls) -> "NewsCalendar":
        return cls([])

    @classmethod
    def from_csv(cls, path: Path) -> "NewsCalendar":
        """Load from a CSV with columns: datetime_utc, currency, title, impact.

        datetime_utc format: ISO 8601 (e.g. 2026-05-01T13:30:00+00:00)
        """
        events: list[NewsEvent] = []
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    dt = datetime.fromisoformat(row["datetime_utc"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    events.append(
                        NewsEvent(
                            event_time=dt,
                            currency=row["currency"].strip().upper(),
                            title=row["title"].strip(),
                            impact=row["impact"].strip().lower(),
                        )
                    )
                except (KeyError, ValueError) as exc:
                    log.warning("news_calendar.parse_error", extra={"row": row, "error": str(exc)})
        log.info("news_calendar.loaded", extra={"source": str(path), "events": len(events)})
        return cls(events)

    @classmethod
    def from_json(cls, path: Path) -> "NewsCalendar":
        """Load from JSON list of {datetime_utc, currency, title, impact}."""
        data = json.loads(path.read_text(encoding="utf-8"))
        events: list[NewsEvent] = []
        for item in data:
            try:
                dt = datetime.fromisoformat(item["datetime_utc"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                events.append(
                    NewsEvent(
                        event_time=dt,
                        currency=item["currency"].strip().upper(),
                        title=item["title"].strip(),
                        impact=item.get("impact", "high").strip().lower(),
                    )
                )
            except (KeyError, ValueError) as exc:
                log.warning("news_calendar.parse_error", extra={"item": item, "error": str(exc)})
        log.info("news_calendar.loaded", extra={"source": str(path), "events": len(events)})
        return cls(events)

    def events_near(
        self, currencies: frozenset[str], now: datetime, window_seconds: int
    ) -> list[NewsEvent]:
        """Return high-impact events within window_seconds of now that match currencies."""
        lo = now - timedelta(seconds=window_seconds)
        hi = now + timedelta(seconds=window_seconds)
        return [
            e for e in self._events
            if e.is_high_impact()
            and lo <= e.event_time <= hi
            and e.currency in currencies
        ]

    def __len__(self) -> int:
        return len(self._events)


# ---------------------------------------------------------------------------
# Blackout gate
# ---------------------------------------------------------------------------


class NewsBlackoutGate:
    """Pre-trade gate that enforces the news-window restriction.

    Parameters
    ----------
    calendar:
        Loaded NewsCalendar.
    window_minutes:
        Block window around each event (default 2 = ±2 min). FTMO specifies 2.
    """

    def __init__(
        self,
        calendar: NewsCalendar,
        window_minutes: int = 2,
    ) -> None:
        self._calendar = calendar
        self._window_seconds = window_minutes * 60

    def is_blackout(
        self,
        symbol: str,
        now: datetime | None = None,
        account_type: FTMOAccountType | None = None,
    ) -> bool:
        """True if trading symbol at time now is inside a news blackout window.

        If account_type is provided and the news restriction doesn't apply
        to that account type, returns False immediately.
        """
        if account_type is not None and not account_type.news_restriction_applies():
            return False

        if now is None:
            now = utc_now()

        currencies = self._currencies_for(symbol)
        if not currencies:
            return False

        events = self._calendar.events_near(currencies, now, self._window_seconds)
        if events:
            log.warning(
                "risk.news_blackout",
                extra={
                    "symbol": symbol,
                    "events": [e.title for e in events],
                    "now": now.isoformat(),
                },
            )
            return True
        return False

    def next_clear_time(self, symbol: str, now: datetime | None = None) -> datetime | None:
        """Return the earliest time after now when symbol is no longer in a blackout.

        Returns None if no upcoming blackout in the calendar.
        """
        if now is None:
            now = utc_now()

        currencies = self._currencies_for(symbol)
        if not currencies:
            return None

        events = self._calendar.events_near(currencies, now, self._window_seconds * 10)
        if not events:
            return None

        window = timedelta(seconds=self._window_seconds)
        clear = now
        for event in events:
            end_of_window = event.event_time + window
            if end_of_window > clear:
                clear = end_of_window
        return clear if clear > now else None

    def reload(self, path: Path) -> None:
        """Hot-reload the calendar from disk (e.g. weekly refresh)."""
        suffix = path.suffix.lower()
        if suffix == ".csv":
            self._calendar = NewsCalendar.from_csv(path)
        elif suffix == ".json":
            self._calendar = NewsCalendar.from_json(path)
        else:
            raise ValueError(f"Unsupported calendar format: {suffix}")

    @staticmethod
    def _currencies_for(symbol: str) -> frozenset[str]:
        """Map a broker symbol name to the set of relevant currency codes."""
        upper = symbol.upper()
        # Try exact match first (handles US30, DE40, UK100, XAUUSD, etc.)
        currencies = _SYMBOL_CURRENCIES.get(upper)
        if currencies is not None:
            return currencies
        # Strip broker suffixes case-insensitively (e.g. EURUSD.r → EURUSD).
        # rstrip on lowercased form avoids missing uppercase suffix chars after .upper().
        base = symbol.lower().rstrip("0123456789").rstrip(".+rx_micro").upper()
        currencies = _SYMBOL_CURRENCIES.get(base)
        if currencies is not None:
            return currencies
        # Fallback: try first 3 / last 3 characters as currency pair
        if len(base) == 6:
            return frozenset({base[:3], base[3:]})
        return frozenset()
