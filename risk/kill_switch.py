"""
Kill switches — three independent circuit breakers.

  1. daily_kill    — trips when internal daily loss limit is hit.
                     Resets automatically at Prague midnight.
  2. max_kill      — trips when internal max loss limit is hit.
                     Requires manual restart (full shutdown).
  3. manual_kill   — trips via file sentinel or explicit call.
                     Persistent across restarts until cleared.

All three are checked in the order pipeline before any order reaches MT5.
Tripping any switch flattens all open positions.

Usage:
    ks = KillSwitchManager(client, state_dir=Path("logs"))
    ks.check()          # raises KillSwitchTripped if any switch is active
    ks.trip_daily()     # flatten + halt until Prague midnight
    ks.trip_max()       # flatten + permanent shutdown
    ks.reset_daily()    # called by equity watcher at Prague midnight
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from utils.log import Events, get_logger

log = get_logger(__name__)


class KillSwitchTripped(RuntimeError):
    """Raised by check() when any kill switch is active."""

    def __init__(self, switch: str, reason: str) -> None:
        super().__init__(f"Kill switch '{switch}' is active: {reason}")
        self.switch = switch
        self.reason = reason


class KillSwitchManager:
    """Thread-safe manager for all three independent kill switches.

    Parameters
    ----------
    client:
        MT5Client — used to flatten positions when a switch trips.
        Pass None in tests.
    state_dir:
        Directory for the manual-kill sentinel file.
    """

    _MANUAL_SENTINEL = "MANUAL_KILL.lock"

    def __init__(
        self,
        client: object | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self._client = client
        self._state_dir = state_dir or Path("logs")
        self._state_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._daily_tripped = False
        self._max_tripped = False

    # ------------------------------------------------------------------ #
    # Status checks                                                        #
    # ------------------------------------------------------------------ #

    @property
    def daily_tripped(self) -> bool:
        with self._lock:
            return self._daily_tripped

    @property
    def max_tripped(self) -> bool:
        with self._lock:
            return self._max_tripped

    @property
    def manual_tripped(self) -> bool:
        return self._sentinel_path.exists()

    @property
    def any_tripped(self) -> bool:
        return self.daily_tripped or self.max_tripped or self.manual_tripped

    def check(self) -> None:
        """Raise KillSwitchTripped if any switch is active. Call before every order."""
        if self.manual_tripped:
            raise KillSwitchTripped("manual", f"sentinel file: {self._sentinel_path}")
        with self._lock:
            if self._max_tripped:
                raise KillSwitchTripped("max", "max loss kill — manual restart required")
            if self._daily_tripped:
                raise KillSwitchTripped("daily", "daily loss kill — resets at Prague midnight")

    # ------------------------------------------------------------------ #
    # Trip methods                                                         #
    # ------------------------------------------------------------------ #

    def trip_daily(self, reason: str = "internal daily loss limit") -> None:
        """Flatten positions and halt until Prague midnight."""
        with self._lock:
            if self._daily_tripped:
                return
            self._daily_tripped = True

        log.error(Events.RISK_KILL_SWITCH, switch="daily", reason=reason)
        self._flatten_all_positions()

    def trip_max(self, reason: str = "internal max loss limit") -> None:
        """Flatten positions and permanently halt. Manual restart only."""
        with self._lock:
            if self._max_tripped:
                return
            self._max_tripped = True

        log.error(Events.RISK_KILL_SWITCH, switch="max", reason=reason)
        self._flatten_all_positions()
        # Also write manual sentinel so the process can't be restarted
        # without explicit human action (clearing the sentinel file).
        self._sentinel_path.write_text(
            f"max_kill tripped: {reason}\nDelete this file to re-enable.",
            encoding="utf-8",
        )

    def trip_manual(self, reason: str = "operator request") -> None:
        """Write the sentinel file. Persists across process restarts."""
        self._sentinel_path.write_text(
            f"manual_kill tripped: {reason}\nDelete this file to re-enable.",
            encoding="utf-8",
        )
        log.error(Events.RISK_KILL_SWITCH, switch="manual", reason=reason)
        self._flatten_all_positions()

    # ------------------------------------------------------------------ #
    # Reset (daily only — max and manual require human action)            #
    # ------------------------------------------------------------------ #

    def reset_daily(self) -> None:
        """Reset the daily kill switch at Prague midnight."""
        with self._lock:
            was_tripped = self._daily_tripped
            self._daily_tripped = False
        if was_tripped:
            log.info("kill_switch.daily_reset")

    # ------------------------------------------------------------------ #
    # Position flattening                                                  #
    # ------------------------------------------------------------------ #

    def _flatten_all_positions(self) -> None:
        if self._client is None:
            log.warning("kill_switch.flatten_skipped", reason="no client")
            return

        try:
            import MetaTrader5 as mt5  # type: ignore[import]

            positions = mt5.positions_get()
            if positions is None or len(positions) == 0:
                log.info("kill_switch.flatten_complete", open_positions=0)
                return

            for pos in positions:
                close_type = (
                    mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY
                    else mt5.ORDER_TYPE_BUY
                )
                tick = mt5.symbol_info_tick(pos.symbol)
                price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": pos.symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "position": pos.ticket,
                    "price": price,
                    "deviation": 20,
                    "magic": 0,
                    "comment": "kill_switch_flatten",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                    retcode = result.retcode if result else "None"
                    log.error(
                        "kill_switch.flatten_failed",
                        symbol=pos.symbol,
                        ticket=pos.ticket,
                        retcode=retcode,
                    )
                else:
                    log.info(
                        "kill_switch.position_closed",
                        symbol=pos.symbol,
                        ticket=pos.ticket,
                        volume=pos.volume,
                    )

            log.info("kill_switch.flatten_complete", open_positions=len(positions))

        except Exception as exc:
            log.error("kill_switch.flatten_error", error=str(exc))

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    @property
    def _sentinel_path(self) -> Path:
        return self._state_dir / self._MANUAL_SENTINEL
