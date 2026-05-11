"""
Unit tests for Milestone 4 execution modules.

Tests are designed to run WITHOUT MetaTrader5 installed.

Modules tested:
  - execution/slicer.py       — TwapSlicer plan() and needs_slicing()
  - execution/reconcile.py    — Reconciler (dry-run mode)
  - execution/router.py       — ExecutionRouter (dry_run=True)
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from execution.reconcile import InternalTrade, Reconciler
from execution.slicer import OrderSlice, SlicePlan, TwapSlicer
from execution.router import ExecutionRouter, RouteRequest, RouteResult
from risk.ftmo import FTMOAccountType, FTMOState, new_state
from risk.kill_switch import KillSwitchManager

UTC = timezone.utc

IC = 100_000.0


# ===========================================================================
# Helpers
# ===========================================================================


def _slicer(
    avg_vol: float = 1000.0,
    threshold: float = 0.01,
    cap: float = 0.10,
    interval: float = 60.0,
) -> TwapSlicer:
    return TwapSlicer(
        avg_bar_volume=avg_vol,
        volume_threshold_pct=threshold,
        participation_cap_pct=cap,
        interval_seconds=interval,
    )


def _internal_trade(pnl: float) -> InternalTrade:
    ts = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    return InternalTrade(
        symbol="EURUSD",
        direction=1,
        volume=1.0,
        entry_price=1.10000,
        exit_price=1.10100,
        net_pnl=pnl,
        commission=3.5,
        entry_time=ts,
        exit_time=ts,
    )


def _ftmo_state() -> FTMOState:
    return new_state(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=IC,
        opening_balance=IC,
    )


def _kill_switch(tmp_path: Path) -> KillSwitchManager:
    return KillSwitchManager(client=None, state_dir=tmp_path)


def _router(tmp_path: Path, dry_run: bool = True) -> ExecutionRouter:
    return ExecutionRouter(
        ftmo_state=_ftmo_state(),
        kill_switch=_kill_switch(tmp_path),
        news_blackout=None,
        slicer=_slicer(),
        dry_run=dry_run,
    )


def _request(
    volume: float = 0.5,
    worst_case_loss: float = 200.0,
    symbol: str = "EURUSD",
    price: float = 1.1000,
) -> RouteRequest:
    try:
        import MetaTrader5 as mt5
        order_type = mt5.ORDER_TYPE_BUY
    except ImportError:
        order_type = 0  # ORDER_TYPE_BUY = 0
    return RouteRequest(
        symbol=symbol,
        order_type=order_type,
        volume=volume,
        price=price,
        worst_case_loss=worst_case_loss,
        now=datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
    )


# ===========================================================================
# TwapSlicer — plan()
# ===========================================================================


class TestTwapSlicerSingleOrder:
    """Orders below the threshold produce a single slice."""

    def test_small_order_returns_single_slice(self) -> None:
        s = _slicer(avg_vol=1000.0, threshold=0.01)
        plan = s.plan(9.0)  # 9 < 10 (1% of 1000)
        assert plan.is_single
        assert len(plan.slices) == 1

    def test_single_slice_has_zero_interval(self) -> None:
        plan = _slicer().plan(5.0)
        assert plan.slices[0].interval_seconds == 0.0

    def test_single_slice_has_full_volume(self) -> None:
        plan = _slicer(avg_vol=1000.0).plan(9.0)
        assert plan.slices[0].volume == pytest.approx(9.0)

    def test_single_slice_reason(self) -> None:
        plan = _slicer().plan(5.0)
        assert plan.reason == "single"

    def test_zero_avg_vol_always_single(self) -> None:
        s = TwapSlicer(avg_bar_volume=0.0)
        plan = s.plan(100.0)
        assert plan.is_single


class TestTwapSlicerTwap:
    """Orders above the threshold produce TWAP slices."""

    def test_large_order_produces_multiple_slices(self) -> None:
        # 50 lots, avg_vol=1000, cap=10% → max 100/slice → ceil(50/100)=1, but min=2
        s = _slicer(avg_vol=1000.0, cap=0.10)
        plan = s.plan(50.0)
        assert len(plan.slices) >= 2

    def test_reason_is_sliced(self) -> None:
        s = _slicer(avg_vol=1000.0, cap=0.10)
        plan = s.plan(50.0)
        assert plan.reason == "sliced"

    def test_first_slice_zero_interval(self) -> None:
        s = _slicer(avg_vol=1000.0, cap=0.10)
        plan = s.plan(50.0)
        assert plan.slices[0].interval_seconds == 0.0

    def test_subsequent_slices_have_interval(self) -> None:
        s = _slicer(avg_vol=1000.0, cap=0.10, interval=30.0)
        plan = s.plan(50.0)
        for sl in plan.slices[1:]:
            assert sl.interval_seconds == 30.0

    def test_total_volume_preserved(self) -> None:
        s = _slicer(avg_vol=1000.0, cap=0.10)
        total = 50.17
        plan = s.plan(total)
        filled = sum(sl.volume for sl in plan.slices)
        assert filled == pytest.approx(total, abs=0.05)

    def test_each_slice_respects_cap(self) -> None:
        avg_vol = 1000.0
        cap = 0.10
        max_per_slice = avg_vol * cap  # 100
        s = _slicer(avg_vol=avg_vol, cap=cap)
        plan = s.plan(500.0)
        for sl in plan.slices[:-1]:  # last may be remainder
            assert sl.volume <= max_per_slice + 0.01

    def test_slice_indices_are_sequential(self) -> None:
        s = _slicer(avg_vol=1000.0, cap=0.10)
        plan = s.plan(300.0)
        for i, sl in enumerate(plan.slices):
            assert sl.slice_index == i

    def test_total_slices_field_correct(self) -> None:
        s = _slicer(avg_vol=1000.0, cap=0.10)
        plan = s.plan(300.0)
        n = len(plan.slices)
        assert all(sl.total_slices == n for sl in plan.slices)

    def test_last_slice_is_last(self) -> None:
        s = _slicer(avg_vol=1000.0, cap=0.10)
        plan = s.plan(300.0)
        assert plan.slices[-1].is_last
        assert not plan.slices[0].is_last

    def test_total_duration_matches_interval_count(self) -> None:
        s = _slicer(avg_vol=1000.0, cap=0.10, interval=60.0)
        plan = s.plan(300.0)
        n = len(plan.slices)
        assert plan.total_duration_seconds == pytest.approx((n - 1) * 60.0)

    def test_minimum_two_slices_when_triggered(self) -> None:
        # Even if one slice would hold the whole order, trigger = at least 2
        s = _slicer(avg_vol=100.0, threshold=0.01, cap=0.50)
        plan = s.plan(2.0)  # 2 > 1 (1% of 100), cap=50 → max_per_slice=50
        assert len(plan.slices) >= 2


class TestTwapSlicerNeedsSlicing:
    def test_below_threshold_false(self) -> None:
        s = _slicer(avg_vol=1000.0, threshold=0.01)
        assert not s.needs_slicing(5.0)

    def test_above_threshold_true(self) -> None:
        s = _slicer(avg_vol=1000.0, threshold=0.01)
        assert s.needs_slicing(50.0)

    def test_zero_avg_vol_false(self) -> None:
        s = TwapSlicer(avg_bar_volume=0.0)
        assert not s.needs_slicing(100.0)


# ===========================================================================
# Reconciler — dry-run (no MT5)
# ===========================================================================


class TestReconcilerDryRun:
    """Reconciler with client=None returns an empty broker deal list."""

    def test_dry_run_report_has_zero_broker_deals(self) -> None:
        r = Reconciler(client=None)
        report = r.run(date(2026, 1, 2), [])
        assert report.broker_deal_count == 0

    def test_dry_run_zero_broker_pnl(self) -> None:
        r = Reconciler(client=None)
        report = r.run(date(2026, 1, 2), [])
        assert report.broker_net_pnl == pytest.approx(0.0)

    def test_dry_run_empty_internal_passes(self) -> None:
        r = Reconciler(client=None)
        report = r.run(date(2026, 1, 2), [])
        assert report.passed is True

    def test_dry_run_with_internal_trades_fails_count_check(self) -> None:
        r = Reconciler(client=None)
        trades = [_internal_trade(100.0), _internal_trade(-50.0)]
        report = r.run(date(2026, 1, 2), trades)
        # Broker has 0 closing deals, internal has 2 → count mismatch
        assert report.passed is False
        assert any("count" in d.lower() for d in report.discrepancies)

    def test_internal_net_pnl_summed_correctly(self) -> None:
        r = Reconciler(client=None)
        trades = [_internal_trade(100.0), _internal_trade(-30.0), _internal_trade(50.0)]
        report = r.run(date(2026, 1, 2), trades)
        assert report.internal_net_pnl == pytest.approx(120.0)

    def test_pnl_discrepancy_sign(self) -> None:
        r = Reconciler(client=None)
        trades = [_internal_trade(100.0)]
        report = r.run(date(2026, 1, 2), trades)
        # broker_net=0, internal=100 → discrepancy = 0 - 100 = -100
        assert report.pnl_discrepancy == pytest.approx(-100.0)

    def test_summary_contains_date(self) -> None:
        r = Reconciler(client=None)
        report = r.run(date(2026, 1, 2), [])
        assert "2026-01-02" in report.summary()

    def test_summary_contains_pass(self) -> None:
        r = Reconciler(client=None)
        report = r.run(date(2026, 1, 2), [])
        assert "PASS" in report.summary()

    def test_summary_contains_fail_on_mismatch(self) -> None:
        r = Reconciler(client=None)
        report = r.run(date(2026, 1, 2), [_internal_trade(100.0)])
        assert "FAIL" in report.summary()

    def test_tolerance_override(self) -> None:
        r = Reconciler(client=None, tolerance=0.01)
        # Internal trades sum to 0.005 — broker sees 0 — discrepancy=0.005 < 0.01 tolerance
        # BUT count mismatch still fires (1 internal vs 0 broker closing deals)
        trades = [_internal_trade(0.005)]
        report = r.run(date(2026, 1, 2), trades, tolerance=200.0)
        # P&L discrepancy is 0.005 < 200 so no P&L discrepancy, but count mismatch
        pnl_discreps = [d for d in report.discrepancies if "P&L" in d]
        assert len(pnl_discreps) == 0  # within tolerance

    def test_report_fields_populated(self) -> None:
        r = Reconciler(client=None)
        trade_date = date(2026, 1, 2)
        report = r.run(trade_date, [_internal_trade(50.0)])
        assert report.date == trade_date
        assert report.internal_trade_count == 1
        assert isinstance(report.discrepancies, list)


# ===========================================================================
# ExecutionRouter — dry-run mode (no MT5)
# ===========================================================================


class TestRouterKillSwitch:
    def test_tripped_daily_rejects_order(self, tmp_path: Path) -> None:
        router = _router(tmp_path)
        router._ks.trip_daily()  # trip without client — no flatten attempted
        result = router.route(_request(), equity=IC)
        assert result.allowed is False
        assert "kill_switch" in result.reject_reason

    def test_tripped_manual_rejects_order(self, tmp_path: Path) -> None:
        router = _router(tmp_path)
        router._ks.trip_manual()
        result = router.route(_request(), equity=IC)
        assert result.allowed is False
        assert "kill_switch" in result.reject_reason

    def test_reset_daily_allows_order(self, tmp_path: Path) -> None:
        router = _router(tmp_path)
        router._ks.trip_daily()
        router._ks.reset_daily()
        result = router.route(_request(), equity=IC)
        assert result.allowed is True


class TestRouterHeadroom:
    def test_safe_order_passes_headroom(self, tmp_path: Path) -> None:
        router = _router(tmp_path)
        result = router.route(_request(worst_case_loss=200.0), equity=IC)
        assert result.allowed is True

    def test_order_exceeding_headroom_rejected(self, tmp_path: Path) -> None:
        router = _router(tmp_path)
        # worst_case_loss brings equity to 94k — within 1% buffer of FTMO daily (95k)
        result = router.route(_request(worst_case_loss=5_500.0), equity=IC)
        assert result.allowed is False
        assert "headroom" in result.reject_reason

    def test_reject_reason_contains_headroom_detail(self, tmp_path: Path) -> None:
        router = _router(tmp_path)
        result = router.route(_request(worst_case_loss=99_000.0), equity=IC)
        assert "headroom" in result.reject_reason


class TestRouterDryRun:
    def test_dry_run_returns_allowed(self, tmp_path: Path) -> None:
        router = _router(tmp_path, dry_run=True)
        result = router.route(_request(), equity=IC)
        assert result.allowed is True

    def test_dry_run_no_send_results(self, tmp_path: Path) -> None:
        router = _router(tmp_path, dry_run=True)
        result = router.route(_request(), equity=IC)
        assert len(result.send_results) == 0

    def test_dry_run_has_slice_plan(self, tmp_path: Path) -> None:
        router = _router(tmp_path, dry_run=True)
        result = router.route(_request(volume=0.1), equity=IC)
        assert result.slice_plan is not None

    def test_dry_run_large_order_produces_twap_plan(self, tmp_path: Path) -> None:
        # avg_vol=1000, 0.5 lot < threshold (10 lots) → single; use slicer with small avg_vol
        slicer = TwapSlicer(avg_bar_volume=0.5, participation_cap_pct=0.10)
        router = ExecutionRouter(
            ftmo_state=_ftmo_state(),
            kill_switch=_kill_switch(tmp_path),
            slicer=slicer,
            dry_run=True,
        )
        result = router.route(_request(volume=5.0, worst_case_loss=200.0), equity=IC)
        assert result.allowed is True
        assert result.slice_plan is not None
        assert not result.slice_plan.is_single

    def test_send_results_empty_when_dry_run(self, tmp_path: Path) -> None:
        router = _router(tmp_path, dry_run=True)
        result = router.route(_request(), equity=IC)
        assert len(result.send_results) == 0

    def test_total_volume_filled_zero_in_dry_run(self, tmp_path: Path) -> None:
        router = _router(tmp_path, dry_run=True)
        result = router.route(_request(), equity=IC)
        assert result.total_volume_filled == 0.0


class TestRouterNewsBlackout:
    """News blackout gate is skipped for challenge accounts."""

    def test_news_blackout_skipped_for_challenge_account(self, tmp_path: Path) -> None:
        from risk.news_blackout import NewsBlackoutGate

        # Challenge account — news_restriction_applies() returns False
        state = new_state(FTMOAccountType.CHALLENGE_2STEP_PHASE1, IC)
        nb = NewsBlackoutGate.__new__(NewsBlackoutGate)  # don't call __init__
        # Patch is_blackout to always return True
        nb.is_blackout = lambda *a, **kw: True  # type: ignore[method-assign]

        router = ExecutionRouter(
            ftmo_state=state,
            kill_switch=_kill_switch(tmp_path),
            news_blackout=nb,
            dry_run=True,
        )
        result = router.route(_request(), equity=IC)
        # Challenge account — news gate is skipped even though is_blackout=True
        assert result.allowed is True

    def test_news_blackout_applied_for_funded_standard(self, tmp_path: Path) -> None:
        from risk.news_blackout import NewsBlackoutGate

        state = new_state(FTMOAccountType.FUNDED_STANDARD, IC)
        nb = NewsBlackoutGate.__new__(NewsBlackoutGate)
        nb.is_blackout = lambda *a, **kw: True  # type: ignore[method-assign]

        router = ExecutionRouter(
            ftmo_state=state,
            kill_switch=_kill_switch(tmp_path),
            news_blackout=nb,
            dry_run=True,
        )
        result = router.route(_request(), equity=IC)
        assert result.allowed is False
        assert "news_blackout" in result.reject_reason
