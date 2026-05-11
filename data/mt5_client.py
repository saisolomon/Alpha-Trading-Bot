"""
MT5Client — thin, singleton-safe wrapper around the MetaTrader5 Python package.

Responsibilities:
  - Establish and tear down the MT5 terminal connection.
  - Retry on transient failures with exponential back-off.
  - Expose typed helpers for OHLCV, tick, and symbol-info fetches.
  - Every MT5 call captures last_error() immediately on failure (it resets on
    the next failing call).

Usage:
    from data.mt5_client import MT5Client
    client = MT5Client.from_config(cfg.mt5)
    with client:
        bars = client.fetch_ohlcv("EURUSD", mt5.TIMEFRAME_H1, start, end)
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime
from typing import Generator

import numpy as np
import pandas as pd

from utils.config import MT5Config
from utils.log import Events, get_logger
from utils.timeutils import utc_now

log = get_logger(__name__)

# Lazy import so unit tests without a real MT5 install can still import this module.
try:
    import MetaTrader5 as mt5  # type: ignore[import]

    _MT5_AVAILABLE = True
except ImportError:  # pragma: no cover
    mt5 = None  # type: ignore[assignment]
    _MT5_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RETRIES = 5
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 30.0

# Retryable return codes (requote, off-quotes, server busy)
_RETRYABLE_RETCODES: frozenset[int] = frozenset(
    [
        10004,  # TRADE_RETCODE_REQUOTE
        10006,  # TRADE_RETCODE_REJECT
        10007,  # TRADE_RETCODE_CANCEL
        10018,  # TRADE_RETCODE_MARKET_CLOSED
        10021,  # TRADE_RETCODE_NO_MONEY (transient in some broker builds)
        10025,  # TRADE_RETCODE_TOO_MANY_REQUESTS
        10030,  # TRADE_RETCODE_PLACED (pending — not an error, kept for reference)
    ]
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MT5Error(RuntimeError):
    """Raised when an MT5 operation fails after all retries."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


class MT5NotAvailableError(MT5Error):
    """Raised when the MetaTrader5 package is not installed."""


class MT5ConnectionError(MT5Error):
    """Raised when the terminal is unreachable."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_mt5() -> None:
    if not _MT5_AVAILABLE:
        raise MT5NotAvailableError(
            "The MetaTrader5 package is not installed. "
            "Run: pip install MetaTrader5  (Windows only)"
        )


def _last_error() -> tuple[int, str]:
    """Capture last_error immediately — it is overwritten by the next failing call."""
    err = mt5.last_error()
    return err[0], err[1]


def _backoff(attempt: int) -> None:
    delay = min(_BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_MAX_SECONDS)
    log.warning("mt5.backoff", attempt=attempt, delay_seconds=delay)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# MT5Client
# ---------------------------------------------------------------------------


class MT5Client:
    """Singleton-safe MT5 connection wrapper.

    Create via MT5Client.from_config() or MT5Client(login, password, server).
    Use as a context manager to guarantee shutdown:

        with MT5Client.from_config(cfg.mt5) as client:
            ...
    """

    _instance: MT5Client | None = None

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        path: str = "",
    ) -> None:
        _require_mt5()
        self._login = login
        self._password = password
        self._server = server
        self._path = path
        self._connected = False

    # ------------------------------------------------------------------ #
    # Factory                                                              #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_config(cls, cfg: MT5Config) -> "MT5Client":
        return cls(
            login=cfg.login,
            password=cfg.password,
            server=cfg.server,
            path=cfg.path,
        )

    # ------------------------------------------------------------------ #
    # Context manager                                                      #
    # ------------------------------------------------------------------ #

    def __enter__(self) -> "MT5Client":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()

    # ------------------------------------------------------------------ #
    # Connection management                                                #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        """Initialize terminal + login, with exponential back-off retries."""
        _require_mt5()
        for attempt in range(_MAX_RETRIES):
            ok = mt5.initialize(self._path) if self._path else mt5.initialize()
            if not ok:
                code, msg = _last_error()
                log.error(
                    Events.MT5_RECONNECT_ATTEMPT,
                    attempt=attempt,
                    error_code=code,
                    error_msg=msg,
                )
                if attempt < _MAX_RETRIES - 1:
                    _backoff(attempt)
                    continue
                raise MT5ConnectionError(
                    f"mt5.initialize() failed after {_MAX_RETRIES} attempts: {msg}",
                    code=code,
                )

            if not mt5.login(self._login, password=self._password, server=self._server):
                code, msg = _last_error()
                mt5.shutdown()
                log.error(
                    Events.MT5_RECONNECT_ATTEMPT,
                    attempt=attempt,
                    error_code=code,
                    error_msg=msg,
                    stage="login",
                )
                if attempt < _MAX_RETRIES - 1:
                    _backoff(attempt)
                    continue
                raise MT5ConnectionError(
                    f"mt5.login() failed after {_MAX_RETRIES} attempts: {msg}",
                    code=code,
                )

            self._connected = True
            info = mt5.account_info()
            log.info(
                Events.MT5_CONNECT,
                login=info.login if info else self._login,
                server=self._server,
                balance=info.balance if info else None,
                currency=info.currency if info else None,
            )
            return

    def disconnect(self) -> None:
        if _MT5_AVAILABLE and self._connected:
            mt5.shutdown()
            self._connected = False
            log.info(Events.MT5_DISCONNECT, login=self._login)

    def is_connected(self) -> bool:
        if not _MT5_AVAILABLE or not self._connected:
            return False
        info = mt5.terminal_info()
        return bool(info and info.connected)

    def ensure_connected(self) -> None:
        """Reconnect if the terminal has dropped."""
        if not self.is_connected():
            log.warning(Events.MT5_RECONNECT_ATTEMPT, reason="terminal_disconnected")
            self.connect()

    # ------------------------------------------------------------------ #
    # Account                                                              #
    # ------------------------------------------------------------------ #

    def account_info(self) -> object:
        """Return raw mt5.AccountInfo namedtuple. Never cached."""
        self.ensure_connected()
        info = mt5.account_info()
        if info is None:
            code, msg = _last_error()
            raise MT5Error(f"account_info() returned None: {msg}", code=code)
        return info

    # ------------------------------------------------------------------ #
    # Symbol helpers                                                       #
    # ------------------------------------------------------------------ #

    def symbol_info(self, symbol: str) -> object:
        self.ensure_connected()
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
        if info is None:
            code, msg = _last_error()
            raise MT5Error(f"symbol_info({symbol!r}) failed: {msg}", code=code)
        return info

    def fetch_symbol_info(self, symbol: str) -> dict[str, object]:
        """Return key contract parameters for symbol as a plain dict.

        Keys: broker_name, contract_size, tick_size, tick_value, point,
              stops_level, freeze_level, filling_mode, spread (in points).
        """
        info = self.symbol_info(symbol)
        return {
            "broker_name": symbol,
            "contract_size": float(info.trade_contract_size),  # type: ignore[attr-defined]
            "tick_size": float(info.trade_tick_size),  # type: ignore[attr-defined]
            "tick_value": float(info.trade_tick_value),  # type: ignore[attr-defined]
            "point": float(info.point),  # type: ignore[attr-defined]
            "stops_level": int(info.trade_stops_level),  # type: ignore[attr-defined]
            "freeze_level": int(info.trade_freeze_level),  # type: ignore[attr-defined]
            "filling_mode": int(info.filling_mode),  # type: ignore[attr-defined]
            "spread": int(info.spread),  # type: ignore[attr-defined]
        }

    def symbol_tick(self, symbol: str) -> object:
        self.ensure_connected()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            code, msg = _last_error()
            raise MT5Error(f"symbol_info_tick({symbol!r}) failed: {msg}", code=code)
        return tick

    # ------------------------------------------------------------------ #
    # Historical data                                                      #
    # ------------------------------------------------------------------ #

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: int,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return a UTC-indexed OHLCV DataFrame. Drops the in-progress (open) bar.

        Columns: open, high, low, close, tick_volume, spread, real_volume.
        Index: DatetimeIndex, UTC, no NaNs in OHLC.
        """
        self.ensure_connected()
        mt5.symbol_select(symbol, True)

        # MT5 requires timezone-aware UTC datetimes
        start_utc = start.replace(tzinfo=start.tzinfo) if start.tzinfo else start
        end_utc = end.replace(tzinfo=end.tzinfo) if end.tzinfo else end

        rates = mt5.copy_rates_range(symbol, timeframe, start_utc, end_utc)
        if rates is None or len(rates) == 0:
            code, msg = _last_error()
            raise MT5Error(
                f"copy_rates_range({symbol}, tf={timeframe}) returned empty: {msg}",
                code=code,
            )

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time").sort_index()

        # Drop the current (open/partial) bar if it extends past our end boundary
        now = utc_now()
        df = df[df.index < pd.Timestamp(now)]

        # Sanity: no NaNs in OHLC
        ohlc = ["open", "high", "low", "close"]
        if df[ohlc].isnull().any().any():
            raise MT5Error(f"fetch_ohlcv({symbol}): NaN in OHLC columns — data corrupted")

        return df

    def fetch_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return a UTC-indexed tick DataFrame.

        Columns: bid, ask, last, volume, time_msc, flags, volume_real.
        """
        self.ensure_connected()
        mt5.symbol_select(symbol, True)

        ticks = mt5.copy_ticks_range(
            symbol, start, end, mt5.COPY_TICKS_ALL
        )
        if ticks is None or len(ticks) == 0:
            code, msg = _last_error()
            raise MT5Error(
                f"copy_ticks_range({symbol}) returned empty: {msg}",
                code=code,
            )

        df = pd.DataFrame(ticks)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time").sort_index()
        return df

    # ------------------------------------------------------------------ #
    # Pre-trade calculations                                               #
    # ------------------------------------------------------------------ #

    def calc_margin(self, action: int, symbol: str, volume: float, price: float) -> float:
        self.ensure_connected()
        margin = mt5.order_calc_margin(action, symbol, volume, price)
        if margin is None:
            code, msg = _last_error()
            raise MT5Error(f"order_calc_margin() failed: {msg}", code=code)
        return float(margin)

    def calc_profit(
        self,
        action: int,
        symbol: str,
        volume: float,
        price_open: float,
        price_close: float,
    ) -> float:
        self.ensure_connected()
        profit = mt5.order_calc_profit(action, symbol, volume, price_open, price_close)
        if profit is None:
            code, msg = _last_error()
            raise MT5Error(f"order_calc_profit() failed: {msg}", code=code)
        return float(profit)

    # ------------------------------------------------------------------ #
    # Version / terminal info (for health checks)                         #
    # ------------------------------------------------------------------ #

    def terminal_version(self) -> tuple[int, int, str]:
        """Return (MetaTrader5 build, build date string, package version)."""
        self.ensure_connected()
        ver = mt5.version()
        return ver  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # Context manager for symbol select/deselect                          #
    # ------------------------------------------------------------------ #

    @contextmanager
    def symbol_active(self, symbol: str) -> Generator[None, None, None]:
        """Ensure symbol is in MarketWatch for the duration of the block."""
        mt5.symbol_select(symbol, True)
        try:
            yield
        finally:
            pass  # leave in MarketWatch — removing is rarely useful
