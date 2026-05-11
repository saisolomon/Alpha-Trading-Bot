"""
Tests for backtest/ftmo_sim.py.

Key acceptance criteria:
  - A known-bad equity curve (engineered to breach the FTMO daily limit)
    must produce FTMOSimReport(passed=False) with correct breach details.
  - A clean equity curve must produce FTMOSimReport(passed=True).
  - Internal kill events are recorded but do NOT set passed=False.
  - The simulator correctly detects intrabar worst-case (equity_low) breaches
    even when bar-close equity appears safe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtest.ftmo_sim import FTMOSimReport, FTMOSimulator, FTMOViolation
from risk.ftmo import FTMOAccountType

UTC = timezone.utc

IC = 100_000.0   # initial capital
ANCHOR = IC      # opening balance = initial capital


def _sim(account_type: FTMOAccountType = FTMOAccountType.CHALLENGE_2STEP_PHASE1) -> FTMOSimulator:
    return FTMOSimulator(account_type=account_type, initial_capital=IC, opening_balance=ANCHOR)


def _eq_series(values: list[float], start: str = "2026-01-02") -> pd.Series:
    """Daily equity series (UTC DatetimeIndex)."""
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx, name="equity")


# ---------------------------------------------------------------------------
# Clean run — must PASS
# ---------------------------------------------------------------------------


def test_sim_pass_on_flat_equity() -> None:
    eq = _eq_series([IC] * 30)
    report = _sim().run(eq)
    assert report.passed is True
    assert report.ftmo_daily_line_breach_count == 0
    assert report.ftmo_max_line_breach_count == 0


def test_sim_pass_on_profitable_run() -> None:
    # Equity grows from 100k to 110k over 30 bars — no drawdown
    eq = _eq_series([IC + i * 333 for i in range(31)])
    report = _sim().run(eq)
    assert report.passed is True
    assert report.ftmo_daily_line_breach_count == 0


def test_sim_pass_with_small_drawdown_within_limits() -> None:
    # Drawdown of 2% (below internal daily kill of 3%)
    eq = _eq_series([IC, IC * 0.99, IC * 0.98, IC * 0.99, IC])
    report = _sim().run(eq)
    # 2% drawdown is inside internal kill (3%) so no internal kill either
    assert report.passed is True
    assert report.internal_daily_kill_count == 0


# ---------------------------------------------------------------------------
# Known-bad runs — must FAIL
# ---------------------------------------------------------------------------


def test_sim_fail_when_equity_breaches_ftmo_daily_line() -> None:
    """Equity drops below the FTMO daily limit (5% of IC = 95k)."""
    # Start at 100k, drop to 94k (below 95k FTMO daily line)
    eq = _eq_series([IC, IC, 94_000.0, IC])
    report = _sim().run(eq)
    assert report.passed is False
    assert report.ftmo_daily_line_breach_count >= 1


def test_sim_fail_records_breach_timestamp() -> None:
    eq = _eq_series([IC, IC, 94_000.0, IC])
    report = _sim().run(eq)
    daily_breaches = [v for v in report.violations if v.violation_type == "daily_ftmo_line"]
    assert len(daily_breaches) >= 1
    # Breach should be on bar 2 (index 2)
    assert daily_breaches[0].bar_index == 2


def test_sim_fail_when_equity_breaches_ftmo_max_line() -> None:
    """Equity drops below 10% max loss (90k)."""
    eq = _eq_series([IC, IC, IC, 89_000.0])
    report = _sim().run(eq)
    assert report.passed is False
    assert report.ftmo_max_line_breach_count >= 1


def test_sim_fail_on_intrabar_equity_low() -> None:
    """Bar-close equity is safe but intrabar low breaches the daily line."""
    # eq_close stays at 96k (safe), but eq_low dips to 94k (breach)
    eq_close = _eq_series([IC, IC, 96_000.0, IC])
    eq_low = _eq_series([IC, IC, 94_000.0, IC])  # intrabar dip below 95k
    report = _sim().run(eq_close, equity_low=eq_low)
    assert report.passed is False
    assert report.ftmo_daily_line_breach_count >= 1


# ---------------------------------------------------------------------------
# Internal kills — recorded but don't fail the account
# ---------------------------------------------------------------------------


def test_internal_daily_kill_recorded_but_not_ftmo_fail() -> None:
    """Internal daily kill (at 3%) should be recorded but not set passed=False
    because the FTMO line (5%) was not crossed."""
    # Drop to 96.5k — crosses internal daily kill (97k) but not FTMO daily (95k)
    eq = _eq_series([IC, IC, 96_500.0, IC])
    report = _sim().run(eq)
    assert report.passed is True  # FTMO lines not breached
    assert report.internal_daily_kill_count >= 1


def test_internal_max_kill_recorded_but_not_ftmo_fail() -> None:
    """Internal max kill (at 7% = 93k) fires, but FTMO max (10% = 90k) is not crossed.

    With opening_balance=90k: daily_kill=87k, max_kill=93k, ftmo_daily=85k, ftmo_max=90k.
    Equity at 91k sits in [90k, 93k) — only internal max kill fires.
    """
    sim = FTMOSimulator(
        account_type=FTMOAccountType.CHALLENGE_2STEP_PHASE1,
        initial_capital=IC,
        opening_balance=90_000.0,  # low anchor → daily kill at 87k, max kill at 93k
    )
    # Bar 0 at 90k (opening), bar 1 drops into internal max kill zone but above FTMO lines
    eq = _eq_series([90_000.0, 91_000.0])
    report = sim.run(eq)
    assert report.passed is True
    assert report.internal_max_kill_count >= 1


# ---------------------------------------------------------------------------
# Distances
# ---------------------------------------------------------------------------


def test_min_daily_distance_correct() -> None:
    # Equity at 96k; daily limit = 95k; distance = 1k
    eq = _eq_series([IC, 96_000.0])
    report = _sim().run(eq)
    # distance should be ≈ 1000 (96k - 95k)
    assert report.min_daily_distance == pytest.approx(1_000.0, abs=50.0)


def test_min_daily_distance_negative_on_breach() -> None:
    eq = _eq_series([IC, 94_000.0])
    report = _sim().run(eq)
    assert report.min_daily_distance < 0


# ---------------------------------------------------------------------------
# Best Day ratio — 1-Step only
# ---------------------------------------------------------------------------


def test_best_day_ratio_zero_for_2step() -> None:
    eq = _eq_series([IC] * 10)
    report = _sim(FTMOAccountType.CHALLENGE_2STEP_PHASE1).run(eq)
    assert report.peak_best_day_ratio == 0.0


# ---------------------------------------------------------------------------
# Report summary string
# ---------------------------------------------------------------------------


def test_summary_contains_pass_or_fail() -> None:
    eq = _eq_series([IC] * 10)
    report = _sim().run(eq)
    summary = report.summary()
    assert "PASS" in summary or "FAIL" in summary


def test_summary_fail_includes_violation_details() -> None:
    eq = _eq_series([IC, IC, 94_000.0])
    report = _sim().run(eq)
    summary = report.summary()
    assert "FAIL" in summary
    assert "BREACH" in summary


# ---------------------------------------------------------------------------
# Walk-forward: simulate a multi-day run with Prague reset
# ---------------------------------------------------------------------------


def test_sim_multi_day_with_reset() -> None:
    """Run 10 days of equity; verify no false positives on normal trading."""
    daily_eq = [IC + i * 50 for i in range(10)]  # slow growth, safe
    eq = _eq_series(daily_eq)
    report = _sim().run(eq)
    assert report.passed is True
    assert report.ftmo_daily_line_breach_count == 0
