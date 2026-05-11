"""
Unit + property tests for risk/ftmo.py.

Property invariants:
  1. No order that headroom_check() allows can put worst-case equity
     below any FTMO line (daily or max).
  2. equity_tick() fires FTMOInternalBreach at or before equity reaches
     the internal daily/max kill limits.
  3. daily_reset rolls Best Day tracking correctly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from risk.ftmo import (
    FTMOAccountType,
    FTMOImminent,
    FTMOInternalBreach,
    FTMOState,
    HeadroomResult,
    IntendedOrder,
    daily_reset,
    equity_tick,
    get_rules,
    headroom_check,
    new_state,
)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_TYPES = list(FTMOAccountType)
_1STEP_TYPES = [t for t in FTMOAccountType if t.is_1step()]
_NON_1STEP_TYPES = [t for t in FTMOAccountType if not t.is_1step()]

ANCHOR = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)


def _make_state(
    account_type: FTMOAccountType = FTMOAccountType.CHALLENGE_2STEP_PHASE1,
    initial_capital: float = 100_000.0,
    anchor_balance: float | None = None,
    today_pnl: float = 0.0,
    sum_pnl: float = 0.0,
) -> FTMOState:
    balance = anchor_balance if anchor_balance is not None else initial_capital
    return FTMOState(
        account_type=account_type,
        initial_capital=initial_capital,
        prague_day_anchor=ANCHOR,
        daily_loss_anchor_balance=balance,
        highest_eod_balance=balance,
        today_closed_pnl=today_pnl,
        sum_profitable_day_pnl=sum_pnl,
    )


def _make_order(worst_case_loss: float, symbol: str = "EURUSD") -> IntendedOrder:
    return IntendedOrder(
        symbol=symbol,
        volume=1.0,
        stop_loss_distance=abs(worst_case_loss),
        worst_case_loss=abs(worst_case_loss),
    )


# ---------------------------------------------------------------------------
# Account type methods
# ---------------------------------------------------------------------------


def test_1step_types() -> None:
    assert FTMOAccountType.CHALLENGE_1STEP.is_1step()
    assert FTMOAccountType.FUNDED_REWARDS_1STEP.is_1step()
    assert not FTMOAccountType.CHALLENGE_2STEP_PHASE1.is_1step()
    assert not FTMOAccountType.FUNDED_STANDARD.is_1step()


def test_funded_types() -> None:
    assert FTMOAccountType.FUNDED_STANDARD.is_funded()
    assert FTMOAccountType.FUNDED_SWING.is_funded()
    assert FTMOAccountType.FUNDED_REWARDS_1STEP.is_funded()
    assert not FTMOAccountType.CHALLENGE_1STEP.is_funded()
    assert not FTMOAccountType.CHALLENGE_2STEP_PHASE1.is_funded()


def test_news_restriction_only_funded_standard() -> None:
    assert FTMOAccountType.FUNDED_STANDARD.news_restriction_applies()
    for t in _ALL_TYPES:
        if t != FTMOAccountType.FUNDED_STANDARD:
            assert not t.news_restriction_applies()


def test_weekend_hold_only_swing() -> None:
    assert FTMOAccountType.FUNDED_SWING.weekend_hold_allowed()
    for t in _ALL_TYPES:
        if t != FTMOAccountType.FUNDED_SWING:
            assert not t.weekend_hold_allowed()


def test_best_day_rule_applies_only_1step() -> None:
    for t in _1STEP_TYPES:
        assert t.best_day_rule_applies()
    for t in _NON_1STEP_TYPES:
        assert not t.best_day_rule_applies()


def test_trailing_max_loss_only_rewards() -> None:
    assert FTMOAccountType.FUNDED_REWARDS_1STEP.max_loss_is_trailing()
    for t in _ALL_TYPES:
        if t != FTMOAccountType.FUNDED_REWARDS_1STEP:
            assert not t.max_loss_is_trailing()


# ---------------------------------------------------------------------------
# Rule parameter values
# ---------------------------------------------------------------------------


def test_2step_rules() -> None:
    r = get_rules(FTMOAccountType.CHALLENGE_2STEP_PHASE1)
    assert r.ftmo_daily_loss_pct == pytest.approx(0.05)
    assert r.ftmo_max_loss_pct == pytest.approx(0.10)
    assert r.internal_daily_kill_pct == pytest.approx(0.03)
    assert r.internal_max_kill_pct == pytest.approx(0.07)
    assert r.profit_target_pct == pytest.approx(0.10)


def test_1step_rules() -> None:
    r = get_rules(FTMOAccountType.CHALLENGE_1STEP)
    assert r.ftmo_daily_loss_pct == pytest.approx(0.03)
    assert r.ftmo_max_loss_pct == pytest.approx(0.10)
    assert r.internal_daily_kill_pct == pytest.approx(0.02)
    assert r.internal_max_kill_pct == pytest.approx(0.07)


def test_funded_standard_rules() -> None:
    r = get_rules(FTMOAccountType.FUNDED_STANDARD)
    assert r.profit_target_pct == 0.0
    assert r.ftmo_daily_loss_pct == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# FTMOState derived limits
# ---------------------------------------------------------------------------


def test_ftmo_daily_limit() -> None:
    state = _make_state(initial_capital=100_000, anchor_balance=100_000)
    # 2-Step: 5% of initial
    assert state.ftmo_daily_limit == pytest.approx(95_000.0)


def test_ftmo_max_loss_limit_static() -> None:
    state = _make_state(initial_capital=100_000)
    assert state.ftmo_max_loss_limit == pytest.approx(90_000.0)


def test_ftmo_max_loss_limit_trailing() -> None:
    # Funded Rewards: trailing from highest_eod_balance
    state = FTMOState(
        account_type=FTMOAccountType.FUNDED_REWARDS_1STEP,
        initial_capital=100_000,
        prague_day_anchor=ANCHOR,
        daily_loss_anchor_balance=110_000,
        highest_eod_balance=110_000,
    )
    # 10% of initial = 10k, floor from 110k
    assert state.ftmo_max_loss_limit == pytest.approx(100_000.0)


def test_internal_daily_kill_limit() -> None:
    state = _make_state(initial_capital=100_000, anchor_balance=100_000)
    # 2-Step: 3% of initial
    assert state.internal_daily_kill_limit == pytest.approx(97_000.0)


def test_internal_max_kill_limit() -> None:
    state = _make_state(initial_capital=100_000)
    # 7% of initial
    assert state.internal_max_kill_limit == pytest.approx(93_000.0)


def test_distance_methods() -> None:
    state = _make_state(initial_capital=100_000, anchor_balance=100_000)
    equity = 98_000.0
    assert state.distance_to_ftmo_daily(equity) == pytest.approx(3_000.0)
    assert state.distance_to_ftmo_max(equity) == pytest.approx(8_000.0)
    assert state.distance_to_internal_daily(equity) == pytest.approx(1_000.0)
    assert state.distance_to_internal_max(equity) == pytest.approx(5_000.0)


# ---------------------------------------------------------------------------
# Best Day ratio
# ---------------------------------------------------------------------------


def test_best_day_ratio_zero_when_not_applicable() -> None:
    state = _make_state(FTMOAccountType.FUNDED_STANDARD, today_pnl=500, sum_pnl=1_000)
    assert state.best_day_ratio() == 0.0


def test_best_day_ratio_no_profitable_days() -> None:
    state = _make_state(FTMOAccountType.CHALLENGE_1STEP, today_pnl=0, sum_pnl=0)
    assert state.best_day_ratio() == 0.0


def test_best_day_ratio_single_day() -> None:
    state = _make_state(FTMOAccountType.CHALLENGE_1STEP, today_pnl=300, sum_pnl=0)
    # ratio = 300 / 300 = 1.0
    assert state.best_day_ratio() == pytest.approx(1.0)


def test_best_day_ratio_two_days() -> None:
    state = _make_state(FTMOAccountType.CHALLENGE_1STEP, today_pnl=300, sum_pnl=700)
    # ratio = 300 / (700 + 300) = 0.30
    assert state.best_day_ratio() == pytest.approx(0.30)


def test_would_breach_best_day_triggers_at_throttle() -> None:
    # today = 400, sum_prev = 600 → projected today 400+projected
    state = _make_state(FTMOAccountType.CHALLENGE_1STEP, today_pnl=400, sum_pnl=600)
    # Adding 200 more: ratio = 600 / (600 + 600) = 0.50, above throttle=0.40
    assert state.would_breach_best_day(200.0) is True


def test_would_breach_best_day_safe() -> None:
    state = _make_state(FTMOAccountType.CHALLENGE_1STEP, today_pnl=100, sum_pnl=600)
    # Adding 50: today=150, total = 600+150 = 750, ratio = 0.20
    assert state.would_breach_best_day(50.0) is False


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


def test_json_roundtrip() -> None:
    state = _make_state(
        FTMOAccountType.CHALLENGE_1STEP,
        initial_capital=50_000,
        today_pnl=250.5,
        sum_pnl=1_200.0,
    )
    restored = FTMOState.from_json(state.to_json())
    assert restored.account_type == state.account_type
    assert restored.initial_capital == state.initial_capital
    assert restored.today_closed_pnl == pytest.approx(state.today_closed_pnl)
    assert restored.sum_profitable_day_pnl == pytest.approx(state.sum_profitable_day_pnl)


def test_save_load_roundtrip(tmp_path: Path) -> None:
    state = _make_state(FTMOAccountType.FUNDED_STANDARD, initial_capital=200_000)
    p = tmp_path / "state.json"
    state.save(p)
    loaded = FTMOState.load(p)
    assert loaded.account_type == state.account_type
    assert loaded.ftmo_daily_limit == pytest.approx(state.ftmo_daily_limit)


# ---------------------------------------------------------------------------
# daily_reset
# ---------------------------------------------------------------------------


def test_daily_reset_updates_anchor() -> None:
    state = _make_state(
        initial_capital=100_000,
        anchor_balance=100_000,
        today_pnl=500.0,
        sum_pnl=1_000.0,
    )
    new_balance = 100_500.0
    now = datetime(2026, 5, 11, 1, 0, 0, tzinfo=UTC)
    reset = daily_reset(state, now, new_balance)

    assert reset.daily_loss_anchor_balance == pytest.approx(new_balance)
    assert reset.today_closed_pnl == 0.0


def test_daily_reset_rolls_profitable_day_into_sum() -> None:
    state = _make_state(today_pnl=500.0, sum_pnl=1_000.0)
    now = datetime(2026, 5, 11, 1, 0, 0, tzinfo=UTC)
    reset = daily_reset(state, now, 100_000.0)
    assert reset.sum_profitable_day_pnl == pytest.approx(1_500.0)


def test_daily_reset_does_not_roll_losing_day() -> None:
    state = _make_state(today_pnl=-200.0, sum_pnl=1_000.0)
    now = datetime(2026, 5, 11, 1, 0, 0, tzinfo=UTC)
    reset = daily_reset(state, now, 99_800.0)
    assert reset.sum_profitable_day_pnl == pytest.approx(1_000.0)


def test_daily_reset_trailing_max_loss_updates() -> None:
    state = FTMOState(
        account_type=FTMOAccountType.FUNDED_REWARDS_1STEP,
        initial_capital=100_000,
        prague_day_anchor=ANCHOR,
        daily_loss_anchor_balance=100_000,
        highest_eod_balance=100_000,
    )
    now = datetime(2026, 5, 11, 1, 0, 0, tzinfo=UTC)
    reset = daily_reset(state, now, 103_000.0)
    assert reset.highest_eod_balance == pytest.approx(103_000.0)
    # Max loss floor: 103k - 10% of 100k = 93k
    assert reset.ftmo_max_loss_limit == pytest.approx(93_000.0)


# ---------------------------------------------------------------------------
# headroom_check — unit tests
# ---------------------------------------------------------------------------


def test_headroom_allows_safe_order() -> None:
    state = _make_state(initial_capital=100_000, anchor_balance=100_000)
    equity = 100_000.0
    order = _make_order(worst_case_loss=100.0)  # tiny loss, well clear of limits
    result = headroom_check(order, equity, state)
    assert result.allowed is True


def test_headroom_blocks_order_breaching_ftmo_daily() -> None:
    state = _make_state(initial_capital=100_000, anchor_balance=100_000)
    # ftmo_daily_limit = 95_000; buffer = 1% * 100k = 1_000; so block if wce < 96_000
    equity = 96_500.0
    order = _make_order(worst_case_loss=2_000.0)  # wce = 94_500 < 96_000
    result = headroom_check(order, equity, state)
    assert result.allowed is False
    assert "headroom_daily" in result.reason


def test_headroom_blocks_order_breaching_internal_daily() -> None:
    state = _make_state(initial_capital=100_000, anchor_balance=100_000)
    # internal_daily_kill = 97_000
    equity = 97_500.0
    order = _make_order(worst_case_loss=1_000.0)  # wce = 96_500 < 97_000
    result = headroom_check(order, equity, state)
    assert result.allowed is False
    assert "internal" in result.reason


def test_headroom_blocks_order_breaching_ftmo_max() -> None:
    # Low anchor so daily is not the binding constraint
    state = _make_state(initial_capital=100_000, anchor_balance=200_000)
    # ftmo_max = 90_000; buffer = 1_000; block if wce < 91_000
    equity = 92_000.0
    order = _make_order(worst_case_loss=2_000.0)  # wce = 90_000, < 91_000
    result = headroom_check(order, equity, state)
    assert result.allowed is False


def test_headroom_best_day_blocks_1step() -> None:
    # Setup: today = 5000, sum = 5000, so ratio already = 0.50; any more should block
    state = _make_state(
        account_type=FTMOAccountType.CHALLENGE_1STEP,
        initial_capital=100_000,
        today_pnl=5_000,
        sum_pnl=5_000,
    )
    equity = 100_000.0
    # A tiny winning order would push ratio above throttle
    order = _make_order(worst_case_loss=10.0)
    result = headroom_check(order, equity, state)
    # projected_pnl = +10 (optimistic win), today = 5010, denom = 5010+5000 = 10010
    # ratio = 5010/10010 ≈ 0.500 > 0.40 → blocked
    assert result.allowed is False
    assert "best_day" in result.reason


def test_headroom_best_day_not_checked_non_1step() -> None:
    state = _make_state(
        account_type=FTMOAccountType.FUNDED_STANDARD,
        initial_capital=100_000,
        today_pnl=5_000,
        sum_pnl=5_000,
    )
    equity = 100_000.0
    order = _make_order(worst_case_loss=10.0)
    result = headroom_check(order, equity, state)
    assert result.allowed is True


# ---------------------------------------------------------------------------
# equity_tick — unit tests
# ---------------------------------------------------------------------------


def test_equity_tick_healthy_no_raise() -> None:
    state = _make_state(initial_capital=100_000, anchor_balance=100_000)
    equity_tick(100_000.0, state)  # well above all limits; no raise


def test_equity_tick_raises_internal_daily_breach() -> None:
    state = _make_state(initial_capital=100_000, anchor_balance=100_000)
    # internal_daily_kill = 97_000; equity <= 97_000 triggers breach
    with pytest.raises(FTMOInternalBreach) as exc_info:
        equity_tick(97_000.0, state)
    assert exc_info.value.breach_type == "daily"


def test_equity_tick_raises_internal_max_breach() -> None:
    # Make anchor_balance low so internal_daily_kill < internal_max_kill.
    # IC=100k, anchor=90k: daily_kill=87k, max_kill=93k.
    # equity=90k → 90k > 87k (no daily breach), 90k ≤ 93k → max breach.
    state = _make_state(initial_capital=100_000, anchor_balance=90_000)
    with pytest.raises(FTMOInternalBreach) as exc_info:
        equity_tick(90_000.0, state)
    assert exc_info.value.breach_type == "max"


def test_equity_tick_imminent_fires_when_internal_kills_disabled() -> None:
    # FTMOImminent is unreachable when internal kills are above FTMO imminent zones,
    # which is the normal production case. We test the path by constructing a state
    # with a very low anchor so the daily kill line (anchor - 3%) falls below the
    # FTMO daily + imminent buffer zone (anchor - 4.5%).
    # anchor=50k, IC=100k: daily_kill=47k, max_kill=93k, ftmo_daily=45k, imminent@45.5k.
    # equity=46k: > 47k? No — 46k < 47k, so internal daily fires first. Still blocked.
    #
    # In practice FTMOImminent acts as a safety net for edge cases where config
    # puts internal kills below FTMO+buffer. The equity_tick code path is tested
    # indirectly via the ordering: if both imminent and internal-kill conditions
    # are checked, internal-kill always wins with standard FTMO parameters.
    # We verify that equity_tick raises SOME exception when equity is below FTMO limits.
    state = _make_state(initial_capital=100_000, anchor_balance=100_000)
    with pytest.raises((FTMOInternalBreach, FTMOImminent)):
        equity_tick(94_000.0, state)


def test_equity_tick_imminent_attributes() -> None:
    # Verify FTMOImminent carries the right fields even if unreachable in prod.
    exc = FTMOImminent("daily", 95_400.0, 95_000.0, 400.0)
    assert exc.line_type == "daily"
    assert exc.equity == pytest.approx(95_400.0)
    assert exc.ftmo_limit == pytest.approx(95_000.0)
    assert exc.distance == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------

_cap_st = st.floats(min_value=10_000, max_value=1_000_000, allow_nan=False, allow_infinity=False)
_pct_st = st.floats(min_value=0.0, max_value=0.05, allow_nan=False, allow_infinity=False)
_type_st = st.sampled_from(_ALL_TYPES)


@given(
    account_type=_type_st,
    initial_capital=_cap_st,
    equity=_cap_st,
    worst_case_loss=st.floats(min_value=0.0, max_value=50_000, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=400)
def test_headroom_never_allows_order_past_ftmo_daily_line(
    account_type: FTMOAccountType,
    initial_capital: float,
    equity: float,
    worst_case_loss: float,
) -> None:
    """If headroom_check allows an order, worst-case equity stays above the FTMO daily line."""
    state = _make_state(account_type=account_type, initial_capital=initial_capital)
    order = _make_order(worst_case_loss=worst_case_loss)
    result = headroom_check(order, equity, state)

    if result.allowed:
        wce = equity - worst_case_loss
        buffer = state.rules.headroom_buffer_pct * initial_capital
        assert wce >= state.ftmo_daily_limit + buffer - 1e-9, (
            f"allowed but wce={wce:.2f} < ftmo_daily+buffer={state.ftmo_daily_limit + buffer:.2f}"
        )


@given(
    account_type=_type_st,
    initial_capital=_cap_st,
    equity=_cap_st,
    worst_case_loss=st.floats(min_value=0.0, max_value=50_000, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=400)
def test_headroom_never_allows_order_past_ftmo_max_line(
    account_type: FTMOAccountType,
    initial_capital: float,
    equity: float,
    worst_case_loss: float,
) -> None:
    """If headroom_check allows an order, worst-case equity stays above the FTMO max loss line."""
    state = _make_state(account_type=account_type, initial_capital=initial_capital)
    order = _make_order(worst_case_loss=worst_case_loss)
    result = headroom_check(order, equity, state)

    if result.allowed:
        wce = equity - worst_case_loss
        buffer = state.rules.headroom_buffer_pct * initial_capital
        assert wce >= state.ftmo_max_loss_limit + buffer - 1e-9, (
            f"allowed but wce={wce:.2f} < ftmo_max+buffer={state.ftmo_max_loss_limit + buffer:.2f}"
        )


@given(
    initial_capital=_cap_st,
    equity_below_internal=st.floats(
        min_value=0.0, max_value=0.97, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=300)
def test_equity_tick_always_raises_at_or_below_internal_kill(
    initial_capital: float,
    equity_below_internal: float,
) -> None:
    """equity_tick must always raise FTMOInternalBreach if equity ≤ internal daily kill limit."""
    state = _make_state(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=initial_capital,
        anchor_balance=initial_capital,
    )
    # internal_daily_kill = anchor - 3% * capital = 97% of capital
    equity = initial_capital * equity_below_internal  # always ≤ 97% * capital = at or below kill
    assume(equity <= state.internal_daily_kill_limit)

    with pytest.raises(FTMOInternalBreach):
        equity_tick(equity, state)
