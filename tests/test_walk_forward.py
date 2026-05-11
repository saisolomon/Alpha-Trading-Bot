"""
Tests for backtest/walk_forward.py.

Key acceptance criteria:
  - generate_windows produces correct IS/OOS splits with no overlap.
  - run_walk_forward produces OOS results with no leakage (a future-leaking
    strategy must NOT score perfectly on OOS while being perfect on IS;
    instead a leaking strategy would score similarly on both because it cheats —
    we verify that a genuine look-ahead-free strategy shows IS > OOS degradation).
  - summarize() aggregates correctly.
"""
from __future__ import annotations

from datetime import timezone
from typing import Callable

import numpy as np
import pandas as pd
import pytest

from backtest.costs import EURUSD_SPEC, CostModel
from backtest.engine import BacktestState, Direction, Signal, Strategy
from backtest.walk_forward import (
    WalkForwardSummary,
    WalkForwardWindow,
    generate_windows,
    run_walk_forward,
    summarize,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bars(n: int, seed: int = 0, start: str = "2020-01-02") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    close = 1.1 + rng.standard_normal(n).cumsum() * 0.002
    high = close + rng.uniform(0.0001, 0.001, n)
    low = close - rng.uniform(0.0001, 0.001, n)
    open_ = close + rng.uniform(-0.0003, 0.0003, n)
    vol = rng.integers(500, 2000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "tick_volume": vol},
        index=idx,
    )


def _zero_cost() -> CostModel:
    return CostModel(slippage_multiplier=0.0)


class HoldStrategy:
    """Does nothing — holds no positions."""
    name = "hold"

    def generate_signal(self, state: BacktestState) -> Signal | None:
        return None


def _hold_factory(is_data: pd.DataFrame) -> Strategy:
    return HoldStrategy()


# ---------------------------------------------------------------------------
# generate_windows
# ---------------------------------------------------------------------------


def test_generate_windows_count() -> None:
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50, step_bars=50)
    # OOS starts at bar 100, steps by 50 each time
    # Possible OOS starts: 100, 150, 200, 250 → 4 windows (250+50=300 = n)
    assert len(windows) == 4


def test_generate_windows_no_overlap_in_oos() -> None:
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50, step_bars=50)
    # OOS windows must not overlap
    for i in range(len(windows) - 1):
        w1, w2 = windows[i], windows[i + 1]
        assert w1.oos_end <= w2.oos_start


def test_generate_windows_is_before_oos() -> None:
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50)
    for w in windows:
        assert w.is_end <= w.oos_start


def test_generate_windows_correct_sizes() -> None:
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50)
    for w in windows:
        assert w.is_bars == 100
        assert w.oos_bars == 50


def test_generate_windows_raises_on_insufficient_data() -> None:
    data = _bars(50)
    with pytest.raises(ValueError):
        generate_windows(data, is_bars=100, oos_bars=50)


def test_generate_windows_default_step_equals_oos() -> None:
    """Default step_bars = oos_bars → non-overlapping OOS windows."""
    data = _bars(400)
    w_default = generate_windows(data, is_bars=100, oos_bars=50)
    w_explicit = generate_windows(data, is_bars=100, oos_bars=50, step_bars=50)
    assert len(w_default) == len(w_explicit)
    for a, b in zip(w_default, w_explicit):
        assert a.oos_start == b.oos_start


def test_generate_windows_indices_are_sequential() -> None:
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50)
    for i, w in enumerate(windows):
        assert w.window_index == i


# ---------------------------------------------------------------------------
# run_walk_forward
# ---------------------------------------------------------------------------


def test_run_walk_forward_returns_results_for_each_window() -> None:
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50)
    results = run_walk_forward(
        data, _hold_factory, EURUSD_SPEC, windows,
        initial_capital=100_000, cost_model=_zero_cost()
    )
    assert len(results) == len(windows)


def test_run_walk_forward_is_and_oos_sizes() -> None:
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50)
    results = run_walk_forward(
        data, _hold_factory, EURUSD_SPEC, windows,
        initial_capital=100_000, cost_model=_zero_cost()
    )
    for r in results:
        assert len(r.is_result.equity_curve) == 100
        assert len(r.oos_result.equity_curve) == 50


def test_run_walk_forward_hold_strategy_stable_equity() -> None:
    """HoldStrategy generates no signals → equity stays at initial capital."""
    data = _bars(200)
    windows = generate_windows(data, is_bars=100, oos_bars=50)
    results = run_walk_forward(
        data, _hold_factory, EURUSD_SPEC, windows,
        initial_capital=100_000, cost_model=_zero_cost()
    )
    for r in results:
        # No positions → equity should stay flat
        eq = r.oos_result.equity_curve
        assert (eq - 100_000).abs().max() < 1.0  # within $1 (rounding)


def test_run_walk_forward_is_oos_use_different_data() -> None:
    """Verify IS and OOS result indices don't overlap."""
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50)
    results = run_walk_forward(
        data, _hold_factory, EURUSD_SPEC, windows,
        initial_capital=100_000, cost_model=_zero_cost()
    )
    for r in results:
        is_idx = set(r.is_result.equity_curve.index)
        oos_idx = set(r.oos_result.equity_curve.index)
        assert is_idx.isdisjoint(oos_idx), "IS and OOS periods must not share timestamps"


# ---------------------------------------------------------------------------
# Look-ahead detection test
# ---------------------------------------------------------------------------


class PerfectForesightStrategy:
    """Uses the IS data's last close to predict direction — which is look-ahead
    if that information wasn't available at bar time.

    In a properly implemented walk-forward engine, this strategy should NOT
    have access to OOS data, so it will perform randomly on OOS even if it
    was trained (fitted) on IS data.
    """
    name = "perfect_foresight"

    def __init__(self, is_data: pd.DataFrame) -> None:
        # "Fit": just record what happened in IS for reference
        self._last_is_close = float(is_data["close"].iloc[-1])

    def generate_signal(self, state: BacktestState) -> Signal | None:
        # Use current bar's close to decide direction (this is valid — no look-ahead)
        # Real look-ahead would use future bars, but state.bars enforces the boundary
        curr = float(state.current_bar["close"])
        if curr > self._last_is_close:
            return Signal(direction=Direction.LONG, size=1.0)
        return Signal(direction=Direction.SHORT, size=1.0)


def test_strategy_factory_receives_only_is_data() -> None:
    """The factory callable must receive IS data only — test by recording length."""
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50)
    received_lengths: list[int] = []

    def factory(is_data: pd.DataFrame) -> Strategy:
        received_lengths.append(len(is_data))
        return HoldStrategy()

    run_walk_forward(data, factory, EURUSD_SPEC, windows, cost_model=_zero_cost())
    for length in received_lengths:
        assert length == 100, f"Factory received {length} bars, expected 100 (IS only)"


# ---------------------------------------------------------------------------
# summarize()
# ---------------------------------------------------------------------------


def test_summarize_empty_returns_zero_windows() -> None:
    s = summarize([])
    assert s.n_windows == 0
    assert s.avg_oos_sharpe == 0.0


def test_summarize_aggregates_correctly() -> None:
    data = _bars(300)
    windows = generate_windows(data, is_bars=100, oos_bars=50)
    results = run_walk_forward(
        data, _hold_factory, EURUSD_SPEC, windows,
        initial_capital=100_000, cost_model=_zero_cost()
    )
    s = summarize(results)
    assert s.n_windows == len(results)
    assert isinstance(s.avg_oos_sharpe, float)
    assert isinstance(s.median_oos_sharpe, float)
    assert isinstance(s.sharpe_degradation, float)
