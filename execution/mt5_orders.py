"""
MT5 order execution — thin, safe wrapper around mt5.order_send().

Order lifecycle (enforced in this module):
  1. check_order()  — validate against broker rules (margin, stops level, etc.)
  2. send_order()   — execute with retry on retryable errors

FTMO compliance gates (headroom_check, news_blackout, kill_switch) are
enforced in execution/router.py BEFORE this module is called. This module
only handles the broker interaction layer.

Retryable MT5 error codes (requote, off-quotes, server busy):
  10004 REQUOTE, 10014 INVALID_STOPS (transient), 10018 MARKET_CLOSED,
  10021 NO_QUOTES, 10028 TOO_MANY_REQUESTS, 10031 TRADE_DISABLED (transient)

Non-retryable errors fail immediately.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from utils.log import Events, get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy MT5 import (allows tests without MT5 installed)
# ---------------------------------------------------------------------------

try:
    import MetaTrader5 as _mt5  # type: ignore[import]
    _MT5_AVAILABLE = True
except ImportError:
    _mt5 = None  # type: ignore[assignment]
    _MT5_AVAILABLE = False


def _require_mt5() -> Any:
    if not _MT5_AVAILABLE or _mt5 is None:
        raise RuntimeError(
            "MetaTrader5 package is not available. "
            "Install it with: pip install MetaTrader5"
        )
    return _mt5


# ---------------------------------------------------------------------------
# Retryable error codes
# ---------------------------------------------------------------------------

_RETRYABLE_RETCODES = frozenset({
    10004,  # TRADE_RETCODE_REQUOTE
    10021,  # TRADE_RETCODE_NO_QUOTES
    10028,  # TRADE_RETCODE_TOO_MANY_REQUESTS
    10033,  # TRADE_RETCODE_SERVER_BUSY (some brokers)
})

_TERMINAL_RETCODES = frozenset({
    10006,  # TRADE_RETCODE_REJECT
    10007,  # TRADE_RETCODE_CANCEL
    10017,  # TRADE_RETCODE_INVALID
    10025,  # TRADE_RETCODE_INVALID_FILL
    10026,  # TRADE_RETCODE_INVALID_ORDER
    10030,  # TRADE_RETCODE_MARKET_CLOSED
})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of mt5.order_check()."""
    valid: bool
    retcode: int
    balance: float
    equity: float
    profit: float
    margin: float
    margin_free: float
    margin_level: float
    comment: str
    raw: Any = None  # original OrderCheckResult


@dataclass
class SendResult:
    """Result of mt5.order_send()."""
    success: bool
    retcode: int
    order: int       # order ticket
    deal: int        # deal ticket (0 for pending orders)
    volume: float
    price: float
    comment: str
    request_id: int
    raw: Any = None
    attempts: int = 1


# ---------------------------------------------------------------------------
# order_check — MUST be called before every send_order in production
# ---------------------------------------------------------------------------


def check_order(request: dict) -> CheckResult:
    """Validate an order request against broker rules via mt5.order_check().

    Returns CheckResult(valid=True) if the broker accepts the order.
    Does NOT send the order — call send_order() after a successful check.

    Parameters
    ----------
    request:
        MT5 order request dict. Must include at minimum:
        action, symbol, volume, type, price, deviation,
        magic, comment, type_time, type_filling.
    """
    mt5 = _require_mt5()
    result = mt5.order_check(request)
    if result is None:
        err = mt5.last_error()
        log.error(
            "order_check.mt5_error",
            retcode=err[0],
            description=err[1],
            symbol=request.get("symbol"),
        )
        return CheckResult(
            valid=False, retcode=err[0], balance=0, equity=0, profit=0,
            margin=0, margin_free=0, margin_level=0,
            comment=f"mt5 returned None: {err}",
        )

    valid = result.retcode == mt5.TRADE_RETCODE_DONE
    log.debug(
        "order_check.result",
        valid=valid,
        retcode=result.retcode,
        comment=result.comment,
        symbol=request.get("symbol"),
        volume=request.get("volume"),
    )
    return CheckResult(
        valid=valid,
        retcode=result.retcode,
        balance=result.balance,
        equity=result.equity,
        profit=result.profit,
        margin=result.margin,
        margin_free=result.margin_free,
        margin_level=result.margin_level,
        comment=result.comment,
        raw=result,
    )


# ---------------------------------------------------------------------------
# send_order — retries on transient errors
# ---------------------------------------------------------------------------


def send_order(
    request: dict,
    max_retries: int = 3,
    retry_delay_s: float = 0.5,
) -> SendResult:
    """Send a trade request to MT5 with retry on transient errors.

    Parameters
    ----------
    request:
        MT5 OrderRequest dict.
    max_retries:
        Maximum attempts including the first. Default 3.
    retry_delay_s:
        Seconds to wait between retries (doubles each retry).

    Returns
    -------
    SendResult
        SendResult(success=True) only when retcode == TRADE_RETCODE_DONE.
        All other retcodes — including TRADE_RETCODE_PLACED for pending
        orders — return success=False. Callers must check explicitly.

    Notes
    -----
    Captures mt5.last_error() immediately after any failure — it resets
    on the next MT5 call so timing is critical.
    """
    mt5 = _require_mt5()
    delay = retry_delay_s

    for attempt in range(1, max_retries + 1):
        result = mt5.order_send(request)

        if result is None:
            err = mt5.last_error()
            log.error(
                Events.ORDER_REJECTED,
                attempt=attempt,
                symbol=request.get("symbol"),
                retcode=err[0],
                description=err[1],
                reason="mt5_returned_none",
            )
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
            continue

        retcode = result.retcode

        if retcode == mt5.TRADE_RETCODE_DONE:
            log.info(
                Events.ORDER_SENT,
                symbol=result.request.symbol,
                order=result.order,
                deal=result.deal,
                volume=result.volume,
                price=result.price,
                retcode=retcode,
                attempts=attempt,
            )
            return SendResult(
                success=True,
                retcode=retcode,
                order=result.order,
                deal=result.deal,
                volume=result.volume,
                price=result.price,
                comment=result.comment,
                request_id=result.request_id,
                raw=result,
                attempts=attempt,
            )

        if retcode in _RETRYABLE_RETCODES and attempt < max_retries:
            log.warning(
                "order_send.retry",
                attempt=attempt,
                retcode=retcode,
                comment=result.comment,
                symbol=request.get("symbol"),
            )
            time.sleep(delay)
            delay *= 2
            continue

        # Non-retryable failure
        log.error(
            Events.ORDER_REJECTED,
            symbol=request.get("symbol"),
            retcode=retcode,
            comment=result.comment,
            attempts=attempt,
        )
        return SendResult(
            success=False,
            retcode=retcode,
            order=result.order if result else 0,
            deal=result.deal if result else 0,
            volume=request.get("volume", 0),
            price=request.get("price", 0),
            comment=result.comment if result else "",
            request_id=result.request_id if result else 0,
            raw=result,
            attempts=attempt,
        )

    # Exhausted retries
    log.error(
        Events.ORDER_REJECTED,
        symbol=request.get("symbol"),
        reason="max_retries_exhausted",
        attempts=max_retries,
    )
    return SendResult(
        success=False, retcode=-1, order=0, deal=0,
        volume=0, price=0, comment="max_retries_exhausted",
        request_id=0, attempts=max_retries,
    )


# ---------------------------------------------------------------------------
# Margin / profit pre-flight helpers
# ---------------------------------------------------------------------------


def calc_margin(
    action: int,
    symbol: str,
    volume: float,
    price: float,
) -> float | None:
    """Return required margin in account currency, or None on error."""
    mt5 = _require_mt5()
    result = mt5.order_calc_margin(action, symbol, volume, price)
    if result is None:
        err = mt5.last_error()
        log.warning("calc_margin.error", symbol=symbol, error=err)
    return result


def calc_profit(
    action: int,
    symbol: str,
    volume: float,
    price_open: float,
    price_close: float,
) -> float | None:
    """Return projected P&L in account currency, or None on error."""
    mt5 = _require_mt5()
    result = mt5.order_calc_profit(action, symbol, volume, price_open, price_close)
    if result is None:
        err = mt5.last_error()
        log.warning("calc_profit.error", symbol=symbol, error=err)
    return result


# ---------------------------------------------------------------------------
# Order request builder helpers
# ---------------------------------------------------------------------------


def build_market_order(
    symbol: str,
    order_type: int,   # mt5.ORDER_TYPE_BUY or mt5.ORDER_TYPE_SELL
    volume: float,
    price: float,
    sl: float = 0.0,
    tp: float = 0.0,
    deviation: int = 20,
    magic: int = 0,
    comment: str = "",
    filling: int | None = None,
) -> dict:
    """Build a market order request dict.

    Parameters
    ----------
    filling:
        mt5.ORDER_FILLING_IOC, ORDER_FILLING_FOK, or ORDER_FILLING_RETURN.
        If None, defaults to IOC (works on most ECN brokers).
    """
    mt5 = _require_mt5()
    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling if filling is not None else mt5.ORDER_FILLING_IOC,
    }


def build_close_request(position: Any, deviation: int = 20, magic: int = 0) -> dict:
    """Build a market order that closes an existing position.

    Parameters
    ----------
    position:
        A position object from mt5.positions_get() (has .ticket, .symbol,
        .type, .volume attributes).
    """
    mt5 = _require_mt5()
    close_type = (
        mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY
        else mt5.ORDER_TYPE_BUY
    )
    tick = mt5.symbol_info_tick(position.symbol)
    price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": close_type,
        "position": position.ticket,
        "price": price,
        "deviation": deviation,
        "magic": magic,
        "comment": "close_position",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
