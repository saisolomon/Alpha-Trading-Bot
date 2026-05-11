"""
Equity Watcher — sub-second poller of mt5.account_info().equity.

Runs in a background thread. On every tick it calls risk/ftmo.py::equity_tick()
which raises FTMOInternalBreach or FTMOImminent if limits are approached.

The watcher is the last line of defense before an FTMO account failure.
It operates independently of bar-driven strategy logic.

Usage:
    watcher = EquityWatcher(client, state, on_breach=my_handler, on_imminent=my_alert)
    watcher.start()
    # ... trading ...
    watcher.stop()
"""
from __future__ import annotations

import threading
import time
import logging
from datetime import datetime
from typing import Callable

from risk.ftmo import (
    FTMOImminent,
    FTMOInternalBreach,
    FTMOState,
    daily_reset,
    equity_tick,
)
from utils.log import Events, get_logger
from utils.timeutils import is_same_prague_day, utc_now

log = get_logger(__name__)

BreachCallback = Callable[[FTMOInternalBreach, FTMOState], None]
ImminentCallback = Callable[[FTMOImminent, FTMOState], None]


class EquityWatcher:
    """Polls MT5 equity sub-second and enforces internal FTMO limits.

    Parameters
    ----------
    client:
        Connected MT5Client (used for account_info() polls).
    state:
        FTMOState — updated in-place on daily reset.
    poll_interval_ms:
        How often to poll (default 250 ms).
    on_breach:
        Called synchronously when FTMOInternalBreach fires. Must be fast.
        Typically: flatten all positions, set kill_switch.
    on_imminent:
        Called synchronously when FTMOImminent fires. Must be fast.
        Typically: log alert, reduce sizing.
    """

    def __init__(
        self,
        client: object,         # MT5Client — typed as object to avoid circular import
        state: FTMOState,
        poll_interval_ms: int = 250,
        on_breach: BreachCallback | None = None,
        on_imminent: ImminentCallback | None = None,
    ) -> None:
        self._client = client
        self._state = state
        self._interval = poll_interval_ms / 1000.0
        self._on_breach = on_breach
        self._on_imminent = on_imminent

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()

        # Last equity sample (for external inspection)
        self._last_equity: float | None = None
        self._last_poll_time: datetime | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="EquityWatcher", daemon=True
        )
        self._thread.start()
        log.info("equity_watcher.started", poll_interval_ms=int(self._interval * 1000))

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        log.info("equity_watcher.stopped")

    def update_state(self, new_state: FTMOState) -> None:
        """Thread-safe state replacement (e.g. after daily_reset)."""
        with self._state_lock:
            self._state = new_state

    @property
    def last_equity(self) -> float | None:
        return self._last_equity

    @property
    def state(self) -> FTMOState:
        with self._state_lock:
            return self._state

    # ------------------------------------------------------------------ #
    # Internal poll loop                                                   #
    # ------------------------------------------------------------------ #

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                # Never let a poll error kill the watcher thread.
                log.error("equity_watcher.poll_error", error=str(exc))
            time.sleep(self._interval)

    def _tick(self) -> None:
        now = utc_now()

        # Fetch equity from MT5
        try:
            info = self._client.account_info()  # type: ignore[attr-defined]
            equity: float = float(info.equity)
            balance: float = float(info.balance)
        except Exception as exc:
            log.warning("equity_watcher.mt5_error", error=str(exc))
            return

        self._last_equity = equity
        self._last_poll_time = now

        with self._state_lock:
            state = self._state

            # --- Prague midnight rollover ---
            if not is_same_prague_day(state.prague_day_anchor, now):
                state = daily_reset(state, now, balance)
                self._state = state
                log.info(Events.DAILY_RESET, new_daily_limit=state.ftmo_daily_limit)

            # --- Equity tick enforcement ---
            try:
                equity_tick(equity, state, now)
            except FTMOInternalBreach as breach:
                log.error(
                    Events.RISK_KILL_SWITCH,
                    breach_type=breach.breach_type,
                    equity=equity,
                    limit=breach.limit,
                )
                if self._on_breach:
                    self._on_breach(breach, state)
            except FTMOImminent as imminent:
                log.warning(
                    Events.RISK_FTMO_IMMINENT,
                    line_type=imminent.line_type,
                    equity=equity,
                    ftmo_limit=imminent.ftmo_limit,
                    distance=imminent.distance,
                )
                if self._on_imminent:
                    self._on_imminent(imminent, state)

        log.debug(
            Events.EQUITY_TICK,
            equity=equity,
            daily_limit=state.ftmo_daily_limit,
            max_limit=state.ftmo_max_loss_limit,
            distance_daily=state.distance_to_ftmo_daily(equity),
            distance_max=state.distance_to_ftmo_max(equity),
        )
