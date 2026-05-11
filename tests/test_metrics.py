"""
Unit tests for backtest/metrics.py.

All values are hand-calculated or derived from known closed-form results
so that the tests are independent of the implementation.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backtest.engine import Direction, Trade
from backtest.metrics import (
    PerformanceMetrics,
    _cagr,
    _max_drawdown,
    _monthly_returns,
    _returns,
    _sharpe,
    _sortino,
    _total_return,
    _var_cvar,
    compute,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _eq(values: list[float], freq: str = "D") -> pd.Series:
    """Build a daily equity series."""
    idx = pd.date_range("2026-01-02", periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=idx, name="equity")


def _trade(net_pnl: float, entry_bar: int = 0, exit_bar: int = 1) -> Trade:
    ts = datetime(2026, 1, 2, tzinfo=UTC)
    return Trade(
        symbol="EURUSD",
        direction=Direction.LONG,
        entry_price=1.1000,
        exit_price=1.1010,
        size=1.0,
        entry_time=ts,
        exit_time=ts,
        entry_bar=entry_bar,
        exit_bar=exit_bar,
        gross_pnl=net_pnl + 3.5,
        commission=3.5,
        net_pnl=net_pnl,
        exit_reason="signal",
    )


# ---------------------------------------------------------------------------
# _total_return
# ---------------------------------------------------------------------------


def test_total_return_positive() -> None:
    eq = _eq([100_000, 110_000])
    assert _total_return(eq) == pytest.approx(0.10)


def test_total_return_negative() -> None:
    eq = _eq([100_000, 95_000])
    assert _total_return(eq) == pytest.approx(-0.05)


def test_total_return_flat() -> None:
    eq = _eq([100_000, 100_000])
    assert _total_return(eq) == pytest.approx(0.0)


def test_total_return_single_bar() -> None:
    eq = _eq([100_000])
    assert _total_return(eq) == 0.0


# ---------------------------------------------------------------------------
# _cagr
# ---------------------------------------------------------------------------


def test_cagr_one_year_10pct() -> None:
    # 252 daily bars, equity goes from 100k to 110k
    values = [100_000 * (1.10 ** (i / 252)) for i in range(253)]
    eq = _eq(values)
    assert _cagr(eq, 252) == pytest.approx(0.10, abs=1e-3)


def test_cagr_less_than_one_year() -> None:
    # 126 bars (half year), +5% total → should annualize to ~10%
    values = [100_000 * (1.05 ** (i / 126)) for i in range(127)]
    eq = _eq(values)
    cagr = _cagr(eq, 252)
    assert cagr == pytest.approx(0.10, abs=0.01)


# ---------------------------------------------------------------------------
# _max_drawdown
# ---------------------------------------------------------------------------


def test_max_drawdown_simple() -> None:
    eq = _eq([100, 90, 80, 85, 95, 100])
    mdd, dur = _max_drawdown(eq)
    assert mdd == pytest.approx(-0.20)  # 80/100 - 1 = -20%


def test_max_drawdown_no_drawdown() -> None:
    eq = _eq([100, 101, 102, 103, 104])
    mdd, dur = _max_drawdown(eq)
    assert mdd == pytest.approx(0.0)
    assert dur == 0


def test_max_drawdown_duration_counted() -> None:
    # bars 1-3 are below the peak (100): 90, 85, 88 → 3 bars underwater, then bar 4 recovers
    eq = _eq([100, 90, 85, 88, 100, 105])
    _, dur = _max_drawdown(eq)
    assert dur == 3


# ---------------------------------------------------------------------------
# _sharpe
# ---------------------------------------------------------------------------


def test_sharpe_positive_returns() -> None:
    # Constant daily return of 0.1% → Sharpe = (0.001 / 0) → inf, but with some noise
    rng = np.random.default_rng(42)
    daily_returns = 0.001 + rng.normal(0, 0.005, 252)
    eq_vals = [100_000]
    for r in daily_returns:
        eq_vals.append(eq_vals[-1] * (1 + r))
    eq = _eq(eq_vals)
    sh = _sharpe(_returns(eq), 0.0, 252)
    # With mean ~0.1% and std ~0.5%, Sharpe ≈ 0.1/0.5 * sqrt(252) ≈ 3.17
    # Allow ±1.0 for sampling noise over 252 draws
    assert sh == pytest.approx(0.001 / 0.005 * math.sqrt(252), abs=1.0)


def test_sharpe_zero_variance_returns_zero() -> None:
    eq = _eq([100_000] * 10)
    # All returns are 0, std=0 → sharpe=0
    sh = _sharpe(_returns(eq), 0.0, 252)
    assert sh == 0.0


def test_sharpe_negative_mean_is_negative() -> None:
    eq = _eq([100, 99, 98, 97, 96, 95])
    sh = _sharpe(_returns(eq), 0.0, 252)
    assert sh < 0


# ---------------------------------------------------------------------------
# _sortino
# ---------------------------------------------------------------------------


def test_sortino_greater_than_sharpe_when_upside_skew() -> None:
    # Strategy with many small wins and rare losses → sortino >> sharpe
    rng = np.random.default_rng(0)
    returns_arr = np.where(rng.random(500) > 0.1, 0.002, -0.015)
    eq_vals = [100_000]
    for r in returns_arr:
        eq_vals.append(eq_vals[-1] * (1 + r))
    eq = _eq(eq_vals)
    rets = _returns(eq)
    sh = _sharpe(rets, 0.0, 252)
    so = _sortino(rets, 0.0, 252)
    assert so > sh


# ---------------------------------------------------------------------------
# _var_cvar
# ---------------------------------------------------------------------------


def test_var_cvar_normal_distribution() -> None:
    rng = np.random.default_rng(123)
    returns_arr = rng.normal(-0.001, 0.01, 1000)
    eq_vals = [100_000]
    for r in returns_arr:
        eq_vals.append(eq_vals[-1] * (1 + r))
    eq = _eq(eq_vals)
    rets = _returns(eq)
    var, cvar = _var_cvar(rets, 0.95)
    # VaR should be negative
    assert var < 0
    # CVaR should be <= VaR (worse)
    assert cvar <= var


def test_var_cvar_short_series() -> None:
    eq = _eq([100, 99, 98])  # < 10 points
    var, cvar = _var_cvar(_returns(eq), 0.95)
    assert var == 0.0
    assert cvar == 0.0


# ---------------------------------------------------------------------------
# _monthly_returns
# ---------------------------------------------------------------------------


def test_monthly_returns_has_correct_period() -> None:
    # 60 daily bars spanning 3 months
    eq = _eq([100_000 + i * 10 for i in range(65)])
    monthly = _monthly_returns(eq)
    assert len(monthly) >= 2  # at least 2 full months


# ---------------------------------------------------------------------------
# compute() — full integration
# ---------------------------------------------------------------------------


def test_compute_returns_all_fields() -> None:
    rng = np.random.default_rng(7)
    daily_r = rng.normal(0.0005, 0.008, 252)
    eq_vals = [100_000]
    for r in daily_r:
        eq_vals.append(eq_vals[-1] * (1 + r))
    eq = _eq(eq_vals)
    trades = [_trade(50.0, 0, 5), _trade(-20.0, 6, 10), _trade(80.0, 11, 20)]

    m = compute(eq, trades, periods_per_year=252)

    assert isinstance(m.sharpe, float)
    assert isinstance(m.max_drawdown, float)
    assert m.max_drawdown <= 0
    assert 0.0 <= m.win_rate <= 1.0
    assert m.total_trades == 3
    assert m.profit_factor > 0
    assert isinstance(m.monthly_returns, pd.Series)
    assert isinstance(m.rolling_sharpe_12m, pd.Series)


def test_compute_profit_factor() -> None:
    trades = [_trade(100.0), _trade(200.0), _trade(-50.0), _trade(-100.0)]
    eq = _eq([100_000, 100_250, 100_450, 100_400, 100_300])
    m = compute(eq, trades, periods_per_year=252)
    # Gross profit = 300, gross loss = 150, PF = 2.0
    assert m.profit_factor == pytest.approx(2.0)


def test_compute_no_trades() -> None:
    eq = _eq([100_000, 100_000, 100_000])
    m = compute(eq, [], periods_per_year=252)
    assert m.total_trades == 0
    assert m.win_rate == 0.0
    assert m.profit_factor == 0.0


def test_compute_deterministic() -> None:
    """Same inputs must always produce the same outputs."""
    rng = np.random.default_rng(99)
    eq_vals = [100_000 * (1 + rng.normal(0, 0.005)) for _ in range(252)]
    eq = _eq(eq_vals)
    trades = [_trade(50.0), _trade(-30.0)]
    m1 = compute(eq, trades)
    m2 = compute(eq, trades)
    assert m1.sharpe == m2.sharpe
    assert m1.max_drawdown == m2.max_drawdown
    assert m1.cagr == m2.cagr
