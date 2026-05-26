"""
Parse MT5's Experts-tab log files into structured signal events.

MT5 writes per-day log files to:
  <TERMINAL>/MQL5/Logs/<YYYYMMDD>.log

Each line has the format (tab-separated):
  CODE  PID  HH:MM:SS.mmm  <EA-name> (<symbol>,<tf>)  <log message>

We parse the lines matching our EA's `PrintFormat` patterns and emit
typed events the monitor can POST to Convex.

Used incrementally: the parser tracks a high-water-mark byte offset per
file, so each poll only processes NEW lines.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SignalEvent:
    ea_name: str        # e.g. "EURUSD_M15_LondonMomo"
    symbol: str         # e.g. "GBPUSD.sim"
    event_type: str     # "entry" | "skip" | "range_locked" | "trail" | "close"
    side: str | None    # "LONG"/"SHORT" for entries
    price: float | None
    volume: float | None
    event_time_ms: int  # ms since epoch (from log timestamp)
    raw_line: str


# Line patterns we recognise. EAs log in the format:
#   [<EA_NAME>:<symbol>] <message>   OR   [<EA_NAME>] <message>
_ENTRY_RE = re.compile(
    r"\[([\w]+)(?::([\w.]+))?\]\s+ENTRY\s+(LONG|SHORT)?\s*"
    r".*?px=([\d.]+).*?(?:lots=|vol=)([\d.]+)",
    re.IGNORECASE,
)
_SKIP_RE = re.compile(
    r"\[([\w]+)(?::([\w.]+))?\]\s+.*?(?:skip|gate FAIL|too narrow|news blackout)",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    r"\[([\w]+)(?::([\w.]+))?\]\s+.*?(?:range locked|pre-fix locked)",
    re.IGNORECASE,
)
_TRAIL_RE = re.compile(
    r"\[([\w]+)(?::([\w.]+))?\]\s+.*?TRAIL\s+SL",
    re.IGNORECASE,
)
_CLOSE_RE = re.compile(
    r"\[([\w]+)(?::([\w.]+))?\]\s+CLOSED",
    re.IGNORECASE,
)

# Log line prefix: CODE  PID  HH:MM:SS.mmm  EA-name (symbol,TF)  message
# Need to extract the timestamp. Format: tab-separated. Timestamp is field 3.
# Example: "AB\t0\t01:00:00.089\tEURUSD_M15_LondonMomo (EURUSD.sim,M15)\t[EURUSD_M15_LondonMomo:EURUSD.sim] range locked  bars=4 ..."
_LINE_RE = re.compile(r"^[A-Z]+\s+\d+\s+(\d{2}:\d{2}:\d{2})\.\d{3}\s+(.+)$")


def _parse_timestamp(file_date: datetime, hhmmss: str) -> int:
    """Combine the log file's date with the HH:MM:SS from the line.
    Returns ms-since-epoch (UTC)."""
    h, m, s = map(int, hhmmss.split(":"))
    dt = file_date.replace(hour=h, minute=m, second=s, microsecond=0)
    return int(dt.timestamp() * 1000)


def parse_line(file_date: datetime, raw_line: str) -> SignalEvent | None:
    """Parse a single MT5 log line. Returns None if line doesn't match
    any signal-event pattern (most lines)."""
    m = _LINE_RE.match(raw_line.rstrip())
    if not m:
        return None
    hhmmss, rest = m.group(1), m.group(2)
    event_time_ms = _parse_timestamp(file_date, hhmmss)

    # Try patterns in priority order (entry > close > range > skip > trail)
    em = _ENTRY_RE.search(rest)
    if em:
        ea, sym, side, px, vol = em.group(1), em.group(2), em.group(3), em.group(4), em.group(5)
        return SignalEvent(
            ea_name=ea, symbol=sym or "?",
            event_type="entry",
            side=side.upper() if side else None,
            price=float(px), volume=float(vol),
            event_time_ms=event_time_ms,
            raw_line=raw_line.strip()[:300],
        )
    cm = _CLOSE_RE.search(rest)
    if cm:
        ea, sym = cm.group(1), cm.group(2)
        return SignalEvent(
            ea_name=ea, symbol=sym or "?",
            event_type="close",
            side=None, price=None, volume=None,
            event_time_ms=event_time_ms,
            raw_line=raw_line.strip()[:300],
        )
    rm = _RANGE_RE.search(rest)
    if rm:
        ea, sym = rm.group(1), rm.group(2)
        return SignalEvent(
            ea_name=ea, symbol=sym or "?",
            event_type="range_locked",
            side=None, price=None, volume=None,
            event_time_ms=event_time_ms,
            raw_line=raw_line.strip()[:300],
        )
    sm = _SKIP_RE.search(rest)
    if sm:
        ea, sym = sm.group(1), sm.group(2)
        return SignalEvent(
            ea_name=ea, symbol=sym or "?",
            event_type="skip",
            side=None, price=None, volume=None,
            event_time_ms=event_time_ms,
            raw_line=raw_line.strip()[:300],
        )
    tm = _TRAIL_RE.search(rest)
    if tm:
        ea, sym = tm.group(1), tm.group(2)
        return SignalEvent(
            ea_name=ea, symbol=sym or "?",
            event_type="trail",
            side=None, price=None, volume=None,
            event_time_ms=event_time_ms,
            raw_line=raw_line.strip()[:300],
        )
    return None


def parse_log_file_since(
    log_path: Path,
    file_date: datetime,
    last_offset: int = 0,
) -> tuple[list[SignalEvent], int]:
    """Read NEW lines from log_path (since last_offset bytes) and parse.
    Returns (events, new_offset). Tail-friendly."""
    if not log_path.exists():
        return [], 0
    events = []
    try:
        # MT5 logs are UTF-16 LE with BOM
        size = log_path.stat().st_size
        if size < last_offset:
            # File was rotated/truncated; reset
            last_offset = 0
        with log_path.open("rb") as f:
            f.seek(last_offset)
            raw_bytes = f.read()
        new_offset = size
        # Decode (BOM may or may not be at the start of partial reads)
        try:
            text = raw_bytes.decode("utf-16-le", errors="replace")
        except Exception:
            text = raw_bytes.decode("utf-8", errors="replace")
        # Strip any BOM at the start if we read from position 0
        if text.startswith("﻿"):
            text = text[1:]
        for line in text.splitlines():
            ev = parse_line(file_date, line)
            if ev is not None:
                events.append(ev)
        return events, new_offset
    except Exception as e:
        # Don't crash the monitor on parse errors
        import logging
        logging.getLogger(__name__).warning("parse_log_file_since error: %s", e)
        return [], last_offset


def todays_log_path(logs_dir: Path) -> tuple[Path, datetime]:
    """Return the MOST RECENT MT5 log file path + the date it represents.

    MT5 names log files by TERMINAL-LOCAL time, which depends on broker
    server timezone (often GMT+2/+3). So 'today's UTC' file may not
    exist yet, or might be 'yesterday's' on the disk. We just pick the
    most-recently-modified .log file in the dir.
    """
    if not logs_dir.exists():
        return logs_dir / "missing.log", datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = sorted(
        logs_dir.glob("*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        name = datetime.now(timezone.utc).strftime("%Y%m%d") + ".log"
        return logs_dir / name, datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    most_recent = candidates[0]
    # Parse the date from the filename (YYYYMMDD.log)
    try:
        date_str = most_recent.stem  # "20260525"
        file_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    except Exception:
        file_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return most_recent, file_date
