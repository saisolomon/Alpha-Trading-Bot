"""
Structured logging for the FTMO bot.

Usage:
    from utils.log import get_logger, Events
    log = get_logger(__name__)
    log.info(Events.ORDER_SENT, ticket=123456, symbol="EURUSD", volume=0.01)

JSON goes to the log file; human-readable goes to stderr.
Call configure_logging() once at process startup (done automatically on first import).
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# Canonical event names — every structured log event MUST use one of these.
# Never log free-form strings as the event name in production paths.
# ---------------------------------------------------------------------------


class Events:
    # Connectivity
    MT5_CONNECT = "mt5.connect"
    MT5_DISCONNECT = "mt5.disconnect"
    MT5_RECONNECT_ATTEMPT = "mt5.reconnect_attempt"
    MT5_RECONNECT_FAILED = "mt5.reconnect_failed"

    # Signals
    SIGNAL_GENERATED = "signal.generated"
    SIGNAL_FILTERED = "signal.filtered"  # regime filter suppressed it

    # Risk gates
    RISK_GATE_PASSED = "risk.gate_passed"
    RISK_GATE_BLOCKED = "risk.gate_blocked"
    RISK_DD_THRESHOLD = "risk.dd_threshold"       # approaching internal kill
    RISK_FTMO_IMMINENT = "risk.ftmo_imminent"     # within 0.5% of an FTMO line
    RISK_KILL_SWITCH = "risk.kill_switch"          # internal kill fired
    RISK_NEWS_BLACKOUT = "risk.news_blackout"      # news-window block

    # Orders & positions
    ORDER_CHECKED = "order.checked"
    ORDER_SENT = "order.sent"
    ORDER_FILLED = "order.filled"
    ORDER_REJECTED = "order.rejected"
    ORDER_RETRY = "order.retry"
    POSITION_OPENED = "position.opened"
    POSITION_CLOSED = "position.closed"

    # Equity monitor
    EQUITY_TICK = "equity.tick"                   # periodic equity snapshot

    # System
    SESSION_START = "session.start"
    SESSION_STOP = "session.stop"
    DAILY_RESET = "daily.reset"                   # Prague midnight boundary
    RECONCILE_OK = "reconcile.ok"
    RECONCILE_MISMATCH = "reconcile.mismatch"


# ---------------------------------------------------------------------------
# Log directory — resolved relative to the project root (two levels up from
# this file: utils/ → ftmo-bot/ → logs/).
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def configure_logging(
    *,
    level: str = "INFO",
    log_dir: Path | None = None,
    json_to_file: bool = True,
) -> None:
    """Configure structlog for JSON-to-file + human-readable-to-stderr.

    Call exactly once at process startup. Subsequent calls are no-ops.
    """
    if getattr(configure_logging, "_done", False):
        return

    log_dir = log_dir or _LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    # --- stdlib root logger -------------------------------------------------
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # stderr: human-readable
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stderr_handler)

    # rotating file: JSON, one file per day, keep 30 days
    if json_to_file:
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_dir / "ftmo_bot.log",
            when="midnight",
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(file_handler)

    # --- structlog chain ----------------------------------------------------
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # human-readable renderer for stderr
    stderr_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(),
            foreign_pre_chain=shared_processors,
        )
    )

    # JSON renderer for file
    if json_to_file:
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),
                foreign_pre_chain=shared_processors,
            )
        )

    configure_logging._done = True  # type: ignore[attr-defined]


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger. configure_logging() is called if needed."""
    configure_logging()
    return structlog.get_logger(name)
