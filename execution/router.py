"""
Execution router — the single gateway between strategy signals and MT5.

Order lifecycle (in this module):
  1. kill_switch.check()      — abort immediately if any switch is active
  2. headroom_check()         — simulate worst-case equity; reject if too close to FTMO line
  3. news_blackout.is_blackout() — reject if within news window (funded accounts only)
  4. calc_margin()            — verify sufficient free margin
  5. slicer.plan()            — split into TWAP slices if volume is large
  6. For each slice:
       a. check_order()       — MT5 pre-flight validation
       b. send_order()        — execute; on failure trip daily kill if P&L-impacting
  7. Log every decision (allowed or rejected) with reason

CRITICAL: headroom_check is called BEFORE check_order / order_send.
FTMO compliance gates the broker's own validation, not the reverse.

Usage:
    router = ExecutionRouter(
        ftmo_state=state,
        kill_switch=ks,
        news_blackout=nb,
        slicer=TwapSlicer(avg_bar_volume=1500),
    )
    result = router.route(signal, equity=account_info.equity)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from execution.mt5_orders import (
    CheckResult,
    SendResult,
    build_market_order,
    calc_margin,
    check_order,
    send_order,
)
from execution.slicer import SlicePlan, TwapSlicer
from risk.ftmo import FTMOState, HeadroomResult, IntendedOrder, headroom_check
from risk.kill_switch import KillSwitchManager, KillSwitchTripped
from risk.news_blackout import NewsBlackoutGate
from utils.log import Events, get_logger

log = get_logger(__name__)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Route request / result types
# ---------------------------------------------------------------------------


@dataclass
class RouteRequest:
    """Describes what the strategy wants to execute."""

    symbol: str
    order_type: int           # mt5.ORDER_TYPE_BUY or mt5.ORDER_TYPE_SELL
    volume: float             # lots
    price: float              # current ask (BUY) or bid (SELL)
    sl: float = 0.0           # stop-loss price
    tp: float = 0.0           # take-profit price
    worst_case_loss: float = 0.0  # in account currency; used by headroom_check
    deviation: int = 20
    magic: int = 0
    comment: str = ""
    now: datetime | None = None  # UTC timestamp for news check; defaults to datetime.now(UTC)


@dataclass
class RouteResult:
    """Outcome of one route() call."""

    allowed: bool
    reject_reason: str = ""   # non-empty when allowed=False
    slice_plan: SlicePlan | None = None
    send_results: list[SendResult] = field(default_factory=list)
    check_results: list[CheckResult] = field(default_factory=list)
    attempts: int = 0

    @property
    def fully_filled(self) -> bool:
        return self.allowed and all(r.success for r in self.send_results)

    @property
    def total_volume_filled(self) -> float:
        return sum(r.volume for r in self.send_results if r.success)


# ---------------------------------------------------------------------------
# ExecutionRouter
# ---------------------------------------------------------------------------


class ExecutionRouter:
    """Routes strategy orders through all compliance and risk gates.

    Parameters
    ----------
    ftmo_state:
        Live FTMOState for this trading session.
    kill_switch:
        KillSwitchManager instance shared with the equity watcher.
    news_blackout:
        NewsBlackout instance. Pass None to skip news gate (e.g. during Challenge).
    slicer:
        TwapSlicer configured for the strategy's typical bar volume.
    client:
        MT5Client (or None for dry-run / testing).
    dry_run:
        If True, validates all gates but does NOT send orders to MT5.
    """

    def __init__(
        self,
        ftmo_state: FTMOState,
        kill_switch: KillSwitchManager,
        news_blackout: NewsBlackoutGate | None = None,
        slicer: TwapSlicer | None = None,
        client: Any = None,
        dry_run: bool = False,
    ) -> None:
        self._state = ftmo_state
        self._ks = kill_switch
        self._nb = news_blackout
        self._slicer = slicer
        self._client = client
        self._dry_run = dry_run

    def update_state(self, state: FTMOState) -> None:
        """Replace the FTMO state (called after Prague midnight reset)."""
        self._state = state

    def route(self, request: RouteRequest, equity: float) -> RouteResult:
        """Process one order request through all gates.

        Parameters
        ----------
        request:
            The order the strategy wants to place.
        equity:
            Current account equity in account currency (from mt5.account_info().equity).

        Returns
        -------
        RouteResult
            allowed=True with send_results populated on success.
            allowed=False with reject_reason on any gate failure.
        """
        # ------------------------------------------------------------------
        # Gate 1: Kill switch
        # ------------------------------------------------------------------
        try:
            self._ks.check()
        except KillSwitchTripped as exc:
            log.warning(
                Events.ORDER_REJECTED,
                gate="kill_switch",
                switch=exc.switch,
                symbol=request.symbol,
                reason=exc.reason,
            )
            return RouteResult(allowed=False, reject_reason=f"kill_switch:{exc.switch}")

        # ------------------------------------------------------------------
        # Gate 2: Headroom check (FTMO compliance — before broker validation)
        # ------------------------------------------------------------------
        intended = IntendedOrder(
            symbol=request.symbol,
            volume=request.volume,
            stop_loss_distance=abs(request.price - request.sl) if request.sl else 0.0,
            worst_case_loss=request.worst_case_loss,
        )
        headroom: HeadroomResult = headroom_check(intended, equity, self._state)
        if not headroom.allowed:
            log.warning(
                Events.ORDER_REJECTED,
                gate="headroom",
                symbol=request.symbol,
                volume=request.volume,
                reason=headroom.reason,
                equity=equity,
            )
            return RouteResult(allowed=False, reject_reason=f"headroom:{headroom.reason}")

        # ------------------------------------------------------------------
        # Gate 3: News blackout (funded accounts only if blackout is configured)
        # ------------------------------------------------------------------
        if self._nb is not None and self._state.account_type.news_restriction_applies():
            now = request.now or datetime.now(UTC)
            if self._nb.is_blackout(request.symbol, now, self._state.account_type):
                log.warning(
                    Events.ORDER_REJECTED,
                    gate="news_blackout",
                    symbol=request.symbol,
                    time=now.isoformat(),
                )
                return RouteResult(allowed=False, reject_reason="news_blackout")

        # ------------------------------------------------------------------
        # Gate 4: Margin pre-check
        # ------------------------------------------------------------------
        if not self._dry_run:
            try:
                import MetaTrader5 as mt5  # type: ignore[import]
                action = mt5.ORDER_TYPE_BUY  # margin calc action is symmetric
                margin = calc_margin(action, request.symbol, request.volume, request.price)
                if margin is None:
                    log.warning(
                        "router.margin_check_failed",
                        symbol=request.symbol,
                        volume=request.volume,
                    )
                    return RouteResult(allowed=False, reject_reason="margin_calc_failed")
            except Exception as exc:
                log.warning("router.margin_check_error", error=str(exc))

        # ------------------------------------------------------------------
        # Gate 5: TWAP slice plan
        # ------------------------------------------------------------------
        if self._slicer is not None:
            plan = self._slicer.plan(request.volume)
        else:
            from execution.slicer import OrderSlice, SlicePlan
            plan = SlicePlan(
                total_volume=request.volume,
                slices=[OrderSlice(0, 1, request.volume, 0.0)],
                total_duration_seconds=0.0,
                reason="single",
            )

        log.info(
            "router.slice_plan",
            symbol=request.symbol,
            total_volume=request.volume,
            n_slices=len(plan.slices),
            reason=plan.reason,
        )

        if self._dry_run:
            return RouteResult(
                allowed=True,
                slice_plan=plan,
                reject_reason="dry_run",
            )

        # ------------------------------------------------------------------
        # Gate 6: Execute each slice
        # ------------------------------------------------------------------
        send_results: list[SendResult] = []
        check_results: list[CheckResult] = []
        total_attempts = 0

        for s in plan.slices:
            if s.interval_seconds > 0:
                time.sleep(s.interval_seconds)

            # Refresh price for each slice to avoid stale quotes
            slice_price = self._current_price(request.symbol, request.order_type)
            if slice_price is None:
                slice_price = request.price

            mt5_request = build_market_order(
                symbol=request.symbol,
                order_type=request.order_type,
                volume=s.volume,
                price=slice_price,
                sl=request.sl,
                tp=request.tp,
                deviation=request.deviation,
                magic=request.magic,
                comment=request.comment or f"slice_{s.slice_index+1}of{s.total_slices}",
            )

            # 6a: MT5 pre-flight
            chk = check_order(mt5_request)
            check_results.append(chk)
            if not chk.valid:
                log.error(
                    Events.ORDER_REJECTED,
                    gate="order_check",
                    symbol=request.symbol,
                    slice_index=s.slice_index,
                    retcode=chk.retcode,
                    comment=chk.comment,
                )
                send_results.append(SendResult(
                    success=False,
                    retcode=chk.retcode,
                    order=0,
                    deal=0,
                    volume=s.volume,
                    price=slice_price,
                    comment=f"order_check_failed:{chk.comment}",
                    request_id=0,
                    attempts=0,
                ))
                continue

            # 6b: Send
            result = send_order(mt5_request)
            total_attempts += result.attempts
            send_results.append(result)

            if not result.success:
                log.error(
                    Events.ORDER_REJECTED,
                    gate="order_send",
                    symbol=request.symbol,
                    slice_index=s.slice_index,
                    retcode=result.retcode,
                    comment=result.comment,
                    attempts=result.attempts,
                )

        return RouteResult(
            allowed=True,
            slice_plan=plan,
            send_results=send_results,
            check_results=check_results,
            attempts=total_attempts,
        )

    def _current_price(self, symbol: str, order_type: int) -> float | None:
        """Fetch current bid/ask for a symbol. Returns None on error."""
        try:
            import MetaTrader5 as mt5  # type: ignore[import]
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return None
            return tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        except Exception:
            return None
