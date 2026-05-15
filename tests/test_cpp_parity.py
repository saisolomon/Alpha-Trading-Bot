"""
Parity tests: C++ libquant vs the existing pure-Python implementations.

THE CRITICAL TEST. Any divergence here means the live MQL5 EA (which calls
the C++ DLL) would compute different signals than our backtests (which currently
use the pure-Python code). That's the silent-edge-killer failure mode the
multi-language architecture exists to prevent.

Tests are skipped (not failed) when the `quantlib` C++ Python module is not
yet built -- the scaffolding is checked in even when the toolchain is not
installed locally.

To enable these tests:
    1. Install build prerequisites (see cpp/README.md).
    2. Build:
        cd cpp
        cmake -S . -B build -A x64
        cmake --build build --config Release
    3. Copy the .pyd into the venv:
        copy build\\Release\\quantlib.cp311-win_amd64.pyd ..\\.venv\\Lib\\site-packages\\
    4. Re-run pytest -- these tests will activate.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

# Pure-Python references (the current implementations we trust).
from strategies.fx_momentum.sizing import compute_atr as py_compute_atr
from strategies.index_meanrev.signal import (
    _ema as py_ema,
    _atr as py_atr,
    _rolling_z as py_rolling_z,
)

# Try to import the C++ module. If absent, all tests in this file are skipped.
quantlib = pytest.importorskip(
    "quantlib",
    reason="C++ libquant not built -- see cpp/README.md to enable parity tests",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_TOL_RELATIVE = 1e-9
_TOL_ABSOLUTE = 1e-12


def _allclose_with_nan(a: np.ndarray, b: np.ndarray) -> tuple[bool, str]:
    """Compare two arrays element-wise with NaN-equality semantics. Returns
    (ok, error_message). Tighter tolerance than numpy's default."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        return False, f"shape mismatch: {a.shape} vs {b.shape}"
    nan_a = np.isnan(a)
    nan_b = np.isnan(b)
    if not np.array_equal(nan_a, nan_b):
        diff_idx = int(np.argmax(nan_a != nan_b))
        return False, f"NaN positions differ at index {diff_idx}: {a[diff_idx]} vs {b[diff_idx]}"
    mask = ~nan_a
    if mask.sum() == 0:
        return True, ""
    a_v = a[mask]
    b_v = b[mask]
    diff = np.abs(a_v - b_v)
    tol = _TOL_ABSOLUTE + _TOL_RELATIVE * np.abs(b_v)
    bad = diff > tol
    if bad.any():
        i = int(np.argmax(bad))
        return False, (f"value mismatch at masked index {i}: "
                       f"a={a_v[i]:.18g}, b={b_v[i]:.18g}, diff={diff[i]:.3e}")
    return True, ""


def _synth_ohlc(n: int = 500, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(0.0003, 0.012, n)
    closes = 100.0 * np.exp(np.cumsum(log_rets))
    opens = np.concatenate([[100.0], closes[:-1]])
    spread = np.abs(rng.normal(0, 0.006, n)) * closes
    highs = np.maximum(opens, closes) + spread
    lows = np.minimum(opens, closes) - spread
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                          "close": closes}, index=idx)


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_version_string_present():
    v = quantlib.version()
    assert isinstance(v, str) and len(v) > 0


# ---------------------------------------------------------------------------
# EMA parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("span", [5, 10, 20, 50, 200])
def test_ema_matches_pandas(span):
    series = _synth_ohlc(500)["close"]
    py_out = py_ema(series, span).to_numpy()
    cpp_out = np.array(quantlib.compute_ema(series.tolist(), span))
    ok, msg = _allclose_with_nan(cpp_out, py_out)
    assert ok, f"EMA(span={span}) parity failed: {msg}"


# ---------------------------------------------------------------------------
# ATR parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("period", [5, 14, 20, 50])
def test_atr_matches_python(period):
    df = _synth_ohlc(500)
    py_out = py_atr(df["high"], df["low"], df["close"], period).to_numpy()
    cpp_out = np.array(quantlib.compute_atr(
        df["high"].tolist(), df["low"].tolist(),
        df["close"].tolist(), period,
    ))
    ok, msg = _allclose_with_nan(cpp_out, py_out)
    assert ok, f"ATR(period={period}) parity failed: {msg}"


# ---------------------------------------------------------------------------
# Rolling z-score parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lookback", [10, 50, 100, 252])
def test_rolling_zscore_matches_python(lookback):
    df = _synth_ohlc(500)
    rets = np.log(df["close"]).diff()
    cum10 = rets.rolling(10).sum()
    py_out = py_rolling_z(cum10, lookback).to_numpy()
    cpp_out = np.array(quantlib.compute_rolling_zscore(cum10.tolist(), lookback))
    ok, msg = _allclose_with_nan(cpp_out, py_out)
    assert ok, f"rolling_zscore(lookback={lookback}) parity failed: {msg}"


# ---------------------------------------------------------------------------
# Markov forward step
# ---------------------------------------------------------------------------


def test_markov_forward_step_matches_numpy():
    state = [1.0, 0.0, 0.0]
    transition = [0.7, 0.2, 0.1,
                  0.3, 0.5, 0.2,
                  0.1, 0.3, 0.6]  # row-major 3x3
    cpp_out = np.array(quantlib.markov_forward_step(state, transition))
    np_T = np.array(transition).reshape(3, 3)
    np_out = np.array(state) @ np_T
    assert np.allclose(cpp_out, np_out, atol=1e-12)


def test_markov_forward_n_matches_matrix_power():
    state = [0.5, 0.3, 0.2]
    transition = [0.8, 0.1, 0.1,
                  0.2, 0.6, 0.2,
                  0.1, 0.3, 0.6]
    n_steps = 12
    cpp_out = np.array(quantlib.markov_forward_n_steps(state, transition, n_steps))
    np_T = np.array(transition).reshape(3, 3)
    np_out = np.array(state) @ np.linalg.matrix_power(np_T, n_steps)
    assert np.allclose(cpp_out, np_out, atol=1e-10)


def test_transition_matrix_validation():
    good = [0.7, 0.3, 0.4, 0.6]
    bad_sum = [0.5, 0.6, 0.4, 0.6]
    bad_neg = [-0.1, 1.1, 0.5, 0.5]
    assert quantlib.transition_matrix_is_valid(good, 2) is True
    assert quantlib.transition_matrix_is_valid(bad_sum, 2) is False
    assert quantlib.transition_matrix_is_valid(bad_neg, 2) is False


# ---------------------------------------------------------------------------
# REAL DATA parity -- the test that actually catches research-vs-live drift
# ---------------------------------------------------------------------------


def _try_load_real_data():
    try:
        from data.cache import ParquetCache
    except ImportError:
        return None
    cache = ParquetCache()
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=365 * 5)
    df = cache.read("US500", 16408, start.to_pydatetime(), end.to_pydatetime())
    return df if df is not None and not df.empty else None


@pytest.mark.skipif(_try_load_real_data() is None,
                    reason="cached US500 D1 data not available")
def test_real_data_atr_parity():
    df = _try_load_real_data()
    py_out = py_atr(df["high"], df["low"], df["close"], 14).to_numpy()
    cpp_out = np.array(quantlib.compute_atr(
        df["high"].tolist(), df["low"].tolist(),
        df["close"].tolist(), 14,
    ))
    ok, msg = _allclose_with_nan(cpp_out, py_out)
    assert ok, f"REAL DATA ATR parity failed -- this means live MQL5 will diverge from backtest: {msg}"


@pytest.mark.skipif(_try_load_real_data() is None,
                    reason="cached US500 D1 data not available")
def test_real_data_rolling_zscore_parity():
    df = _try_load_real_data()
    rets = np.log(df["close"]).diff()
    cum10 = rets.rolling(10).sum()
    py_out = py_rolling_z(cum10, 252).to_numpy()
    cpp_out = np.array(quantlib.compute_rolling_zscore(cum10.tolist(), 252))
    ok, msg = _allclose_with_nan(cpp_out, py_out)
    assert ok, f"REAL DATA z-score parity failed: {msg}"
