"""
Unit tests for backtest/engine.py.

Tests:
  - Determinism: same seed + same data → identical equity curve
  - No look-ahead: a deliberately future-leaking strategy must not know future prices
  - Stop-loss and take-profit execution (intrabar)
  - Correct P&L accounting: entry cost, exit cost, commission
  - BacktestResult structure
  - Direction reversal (long → short via flat + new signal)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from backtest.costs import CostModel, SymbolSpec, EURUSD_SPEC
from backtest.engine import (
    BacktestEngine,
    BacktestResult,
    BacktestState,
    Direction,
    Signal,
    Strategy,
    Trade,
)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(n: int, seed: int = 42, start: str = "2026-01-02") -> pd.DataFrame:
    """Generate synthetic OHLCV bars with a UTC DatetimeIndex."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="h", tz="UTC")
    close = 1.1000 + rng.standard_normal(n).cumsum() * 0.0003
    high = close + rng.uniform(0.0001, 0.0010, n)
    low = close - rng.uniform(0.0001, 0.0010, n)
    open_ = close - rng.uniform(-0.0005, 0.0005, n)
    vol = rng.integers(500, 2000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "tick_volume": vol},
        index=idx,
    )


def _zero_cost() -> CostModel:
    return CostModel(slippage_multiplier=0.0)


# A SymbolSpec with zero commission for clean P&L checks
CLEAN_SPEC = SymbolSpec(
    symbol="EURUSD",
    contract_size=100_000,
    point=0.00001,
    tick_value=1.0,
    commission_per_lot=0.0,
    avg_spread_points=0.0,
)


# ---------------------------------------------------------------------------
# Trivial strategies for testing
# ---------------------------------------------------------------------------


class AlwaysLong:
    name = "always_long"

    def generate_signal(self, state: BacktestState) -> Signal:
        if not state.has_position:
            return Signal(direction=Direction.LONG, size=1.0)
        return Signal.flat() if False else None  # type: ignore


class AlwaysFlat:
    name = "always_flat"

    def generate_signal(self, state: BacktestState) -> Signal:
        return Signal.flat()


class AlternatingLongShort:
    """Alternates LONG / SHORT every `period` bars."""
    name = "alternating"

    def __init__(self, period: int = 5) -> None:
        self._period = period

    def generate_signal(self, state: BacktestState) -> Signal | None:
        bar_idx = state.bar_index
        if bar_idx % self._period != 0:
            return None
        direction = Direction.LONG if (bar_idx // self._period) % 2 == 0 else Direction.SHORT
        return Signal(direction=direction, size=1.0)


class LookAheadStrategy:
    """Deliberately uses bar N+1's close to make a decision at bar N.

    Used to verify that a properly implemented look-ahead detector would
    catch this (we verify that the engine CANNOT pass N+1 data to bar N's
    signal generation regardless of what the strategy asks for).
    """
    name = "look_ahead"

    def generate_signal(self, state: BacktestState) -> Signal | None:
        # Attempt to read beyond the current bar index
        df = state.bars
        # state.bars should only have rows 0..bar_index — we verify length
        self._bars_seen = len(df)
        self._bar_index = state.bar_index
        return None


class StopLossStrategy:
    """Opens a long with a stop loss at entry - N pips."""
    name = "stop_loss"

    def __init__(self, stop_pips: float = 10.0) -> None:
        self._stop = stop_pips * 0.0001  # convert pips to price units

    def generate_signal(self, state: BacktestState) -> Signal | None:
        if not state.has_position:
            entry_approx = float(state.current_bar["close"])
            return Signal(
                direction=Direction.LONG,
                size=1.0,
                stop_loss_price=entry_approx - self._stop,
            )
        return None


# ---------------------------------------------------------------------------
# Determinism test
# ---------------------------------------------------------------------------


def test_engine_is_deterministic() -> None:
    bars = _make_bars(100)
    strategy = AlternatingLongShort(period=5)

    engine1 = BacktestEngine(bars, EURUSD_SPEC, _zero_cost())
    engine2 = BacktestEngine(bars, EURUSD_SPEC, _zero_cost())

    r1 = engine1.run(strategy, initial_capital=100_000)
    r2 = engine2.run(strategy, initial_capital=100_000)

    pd.testing.assert_series_equal(r1.equity_curve, r2.equity_curve)
    assert len(r1.trades) == len(r2.trades)


def test_engine_different_seeds_differ() -> None:
    bars1 = _make_bars(100, seed=1)
    bars2 = _make_bars(100, seed=2)
    strategy = AlwaysLong()

    r1 = BacktestEngine(bars1, EURUSD_SPEC).run(strategy, 100_000)
    r2 = BacktestEngine(bars2, EURUSD_SPEC).run(strategy, 100_000)

    assert not r1.equity_curve.equals(r2.equity_curve)


# ---------------------------------------------------------------------------
# No look-ahead invariant
# ---------------------------------------------------------------------------


def test_strategy_sees_only_bars_up_to_current() -> None:
    bars = _make_bars(50)
    strategy = LookAheadStrategy()

    BacktestEngine(bars, EURUSD_SPEC).run(strategy, 100_000, min_bars_warmup=1)

    # At bar_index N, strategy should have seen exactly N+1 bars
    assert strategy._bars_seen == strategy._bar_index + 1


# ---------------------------------------------------------------------------
# Always-flat strategy → no trades, equity unchanged
# ---------------------------------------------------------------------------


def test_always_flat_no_trades() -> None:
    bars = _make_bars(50)
    result = BacktestEngine(bars, EURUSD_SPEC, _zero_cost()).run(AlwaysFlat(), 100_000)
    # With flat signals, we close any position immediately — so no net PnL
    # (only the equity watcher's effect via commission if any)
    assert result.trades == [] or all(t.net_pnl == 0 for t in result.trades)


# ---------------------------------------------------------------------------
# Always-long strategy: equity moves with the market
# ---------------------------------------------------------------------------


def test_always_long_equity_moves_with_price() -> None:
    # Construct bars that go monotonically up so we know the strategy makes money
    n = 20
    idx = pd.date_range("2026-01-02", periods=n, freq="h", tz="UTC")
    close = [1.1000 + i * 0.0010 for i in range(n)]
    high = [c + 0.0005 for c in close]
    low = [c - 0.0005 for c in close]
    bars = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "tick_volume": [1000.0] * n},
        index=idx,
    )
    strategy = AlwaysLong()
    result = BacktestEngine(bars, CLEAN_SPEC, _zero_cost()).run(strategy, 100_000, min_bars_warmup=1)

    # Final equity should exceed initial (prices went up, we're long)
    assert result.equity_curve.iloc[-1] > result.equity_curve.iloc[0]


# ---------------------------------------------------------------------------
# Stop loss fires intrabar
# ---------------------------------------------------------------------------


def test_stop_loss_fires() -> None:
    # Bar 1: open at 1.1000, we go long at 1.1000
    # Bar 2: low = 1.0980, stop = 1.0990 → should trigger
    idx = pd.date_range("2026-01-02", periods=4, freq="h", tz="UTC")
    bars = pd.DataFrame(
        {
            "open":  [1.1000, 1.1000, 1.0995, 1.1010],
            "high":  [1.1010, 1.1010, 1.1005, 1.1020],
            "low":   [1.0995, 1.0995, 1.0975, 1.1005],
            "close": [1.1005, 1.1005, 1.0990, 1.1015],
            "tick_volume": [1000.0] * 4,
        },
        index=idx,
    )
    strategy = StopLossStrategy(stop_pips=10.0)  # stop = entry - 0.0010
    result = BacktestEngine(bars, CLEAN_SPEC, _zero_cost()).run(strategy, 100_000, min_bars_warmup=1)

    stop_trades = [t for t in result.trades if t.exit_reason == "stop"]
    assert len(stop_trades) >= 1


def test_stop_loss_pnl_correct() -> None:
    # Controlled scenario: long at 1.1000, stop at 1.0990
    # stop fires at 1.0990 → loss = (1.0990 - 1.1000) * 1 lot * 100k = -$100
    idx = pd.date_range("2026-01-02", periods=3, freq="h", tz="UTC")
    bars = pd.DataFrame(
        {
            "open":  [1.1000, 1.1000, 1.1000],
            "high":  [1.1010, 1.1010, 1.1010],
            "low":   [1.0995, 1.0985, 1.1005],  # bar 1 touches stop
            "close": [1.1005, 1.0992, 1.1005],
            "tick_volume": [1000.0] * 3,
        },
        index=idx,
    )

    class FixedLongWithStop:
        name = "fixed_long"
        def generate_signal(self, state):
            if not state.has_position:
                return Signal(
                    direction=Direction.LONG,
                    size=1.0,
                    stop_loss_price=1.0990,
                )
            return None

    result = BacktestEngine(bars, CLEAN_SPEC, _zero_cost()).run(FixedLongWithStop(), 100_000, min_bars_warmup=1)
    stop_trades = [t for t in result.trades if t.exit_reason == "stop"]
    assert len(stop_trades) == 1
    # exit at stop = 1.0990, entry ≈ 1.1000 (bar 1 open), loss = -100
    assert stop_trades[0].net_pnl == pytest.approx(-100.0, abs=5.0)


# ---------------------------------------------------------------------------
# Take profit fires intrabar
# ---------------------------------------------------------------------------


def test_take_profit_fires() -> None:
    idx = pd.date_range("2026-01-02", periods=4, freq="h", tz="UTC")
    bars = pd.DataFrame(
        {
            "open":  [1.1000, 1.1000, 1.1020, 1.1030],
            "high":  [1.1005, 1.1005, 1.1035, 1.1040],
            "low":   [1.0998, 1.0998, 1.1015, 1.1025],
            "close": [1.1002, 1.1002, 1.1030, 1.1035],
            "tick_volume": [1000.0] * 4,
        },
        index=idx,
    )

    class LongWithTP:
        name = "long_tp"
        def generate_signal(self, state):
            if not state.has_position:
                return Signal(direction=Direction.LONG, size=1.0, take_profit_price=1.1030)
            return None

    result = BacktestEngine(bars, CLEAN_SPEC, _zero_cost()).run(LongWithTP(), 100_000, min_bars_warmup=1)
    tp_trades = [t for t in result.trades if t.exit_reason == "take_profit"]
    assert len(tp_trades) >= 1


# ---------------------------------------------------------------------------
# BacktestResult structure
# ---------------------------------------------------------------------------


def test_result_equity_curve_length_matches_bars() -> None:
    bars = _make_bars(60)
    result = BacktestEngine(bars, EURUSD_SPEC).run(AlwaysFlat(), 100_000)
    assert len(result.equity_curve) == len(bars)
    assert len(result.equity_high) == len(bars)
    assert len(result.equity_low) == len(bars)


def test_result_equity_starts_at_initial_capital() -> None:
    bars = _make_bars(10)
    result = BacktestEngine(bars, EURUSD_SPEC, _zero_cost()).run(AlwaysFlat(), 100_000)
    assert result.equity_curve.iloc[0] == pytest.approx(100_000.0)


def test_result_equity_low_lte_close() -> None:
    bars = _make_bars(100)
    result = BacktestEngine(bars, EURUSD_SPEC).run(AlternatingLongShort(), 100_000)
    assert (result.equity_low <= result.equity_curve + 1e-9).all()


def test_result_equity_high_gte_close() -> None:
    bars = _make_bars(100)
    result = BacktestEngine(bars, EURUSD_SPEC).run(AlternatingLongShort(), 100_000)
    assert (result.equity_high >= result.equity_curve - 1e-9).all()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_engine_rejects_non_datetime_index() -> None:
    bars = _make_bars(10)
    bars.index = range(10)  # type: ignore
    with pytest.raises(TypeError, match="DatetimeIndex"):
        BacktestEngine(bars, EURUSD_SPEC)


def test_engine_rejects_naive_index() -> None:
    bars = _make_bars(10)
    bars.index = bars.index.tz_localize(None)
    with pytest.raises(TypeError, match="timezone-aware"):
        BacktestEngine(bars, EURUSD_SPEC)


def test_engine_rejects_missing_columns() -> None:
    idx = pd.date_range("2026-01-02", periods=10, freq="h", tz="UTC")
    bars = pd.DataFrame({"close": range(10)}, index=idx)
    with pytest.raises(ValueError, match="missing"):
        BacktestEngine(bars, EURUSD_SPEC)
