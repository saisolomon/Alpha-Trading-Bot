"""
Unit tests for strategies/index_meanrev/lstm_signal.py.

Skipped when torch isn't installed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from strategies.index_meanrev.lstm_signal import (
    LSTMConfig,
    LSTMDirectionalGate,
    build_features,
    build_target,
    make_sequences,
    train_lstm_on_window,
)


def _synth_ohlc(n: int = 600, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(0.0003, 0.012, n)
    closes = 100.0 * np.exp(np.cumsum(log_rets))
    opens = np.concatenate([[100.0], closes[:-1]])
    spread = np.abs(rng.normal(0, 0.006, n)) * closes
    highs = np.maximum(opens, closes) + spread
    lows = np.minimum(opens, closes) - spread
    vol = np.abs(rng.normal(1000, 300, n))
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "tick_volume": vol,
    }, index=idx)


# ---------------------------------------------------------------------------
# Features and target
# ---------------------------------------------------------------------------


class TestFeatures:

    def test_columns_present(self):
        df = _synth_ohlc(200)
        feats = build_features(df, LSTMConfig())
        for col in ["ret_1d", "ret_5d", "ret_20d", "vol_ratio",
                     "momentum_norm", "volume_zscore", "range_norm"]:
            assert col in feats.columns

    def test_warmup_is_nan(self):
        df = _synth_ohlc(200)
        feats = build_features(df, LSTMConfig())
        # 20-day return needs at least 20 bars
        assert pd.isna(feats["ret_20d"].iloc[19])
        assert not pd.isna(feats["ret_20d"].iloc[20])

    def test_no_look_ahead(self):
        df = _synth_ohlc(400)
        feats_a = build_features(df, LSTMConfig())
        df_b = df.copy()
        df_b.iloc[201:] *= 1.5  # mutate future
        feats_b = build_features(df_b, LSTMConfig())
        # Features at bar 200 should be unchanged
        for col in feats_a.columns:
            v_a = feats_a[col].iloc[200]
            v_b = feats_b[col].iloc[200]
            if not pd.isna(v_a):
                assert v_a == pytest.approx(v_b, abs=1e-12), col


class TestTarget:

    def test_binary_values(self):
        df = _synth_ohlc(50)
        tgt = build_target(df)
        valid = tgt.dropna()
        assert set(valid.unique()) <= {0, 1}

    def test_last_bar_is_nan(self):
        df = _synth_ohlc(50)
        tgt = build_target(df)
        assert pd.isna(tgt.iloc[-1])


# ---------------------------------------------------------------------------
# Sequence builder
# ---------------------------------------------------------------------------


class TestMakeSequences:

    def test_shapes(self):
        df = _synth_ohlc(400)
        feats = build_features(df, LSTMConfig())
        tgt = build_target(df)
        X, y, idx = make_sequences(feats, tgt, lookback=20)
        assert X.shape[1] == 20
        assert X.shape[2] == feats.shape[1]
        assert X.shape[0] == len(y) == len(idx)

    def test_target_alignment(self):
        """The y at index i should equal the target at the LAST timestamp
        of the sequence at index i (the timestamp the prediction is made at,
        which has a label = direction of t+1)."""
        df = _synth_ohlc(200)
        feats = build_features(df, LSTMConfig())
        tgt = build_target(df)
        X, y, idx = make_sequences(feats, tgt, lookback=20)
        for i in [0, 10, 50, len(y) - 1]:
            ts = idx[i]
            assert y[i] == tgt.loc[ts]


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


class TestTrainer:

    def test_trains_without_crashing(self):
        df = _synth_ohlc(500)
        feats = build_features(df, LSTMConfig())
        tgt = build_target(df)
        config = LSTMConfig(max_epochs=3, patience=2)
        result = train_lstm_on_window(feats, tgt, config)
        assert result is not None
        assert 0.0 <= result.best_val_acc <= 1.0
        assert result.n_train + result.n_val > 0

    def test_insufficient_data_returns_none(self):
        df = _synth_ohlc(50)
        feats = build_features(df, LSTMConfig())
        tgt = build_target(df)
        result = train_lstm_on_window(feats, tgt, LSTMConfig())
        assert result is None


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class TestLSTMDirectionalGate:

    def test_warmup_denies(self):
        df = _synth_ohlc(700)
        gate = LSTMDirectionalGate(
            df, LSTMConfig(max_epochs=2),
            initial_train_bars=500, refit_every=200,
        )
        assert gate.allow_entry(100) is False

    def test_makes_bool_decision_after_warmup(self):
        df = _synth_ohlc(700)
        gate = LSTMDirectionalGate(
            df, LSTMConfig(max_epochs=2),
            initial_train_bars=500, refit_every=200,
        )
        decision = gate.allow_entry(600)
        assert isinstance(decision, bool)

    def test_threshold_one_always_denies(self):
        """Threshold of 1.0 -> P(up) must equal 1.0 to allow, which a
        probabilistic sigmoid never quite reaches."""
        df = _synth_ohlc(700)
        gate = LSTMDirectionalGate(
            df, LSTMConfig(max_epochs=2, long_entry_threshold=1.001),
            initial_train_bars=500, refit_every=200,
        )
        # Test a few bars; expect all False because no sigmoid output > 1.001
        denies = sum(1 for b in range(550, 650, 25) if not gate.allow_entry(b))
        assert denies == len(range(550, 650, 25))

    def test_threshold_zero_always_permits_postwarmup(self):
        df = _synth_ohlc(700)
        gate = LSTMDirectionalGate(
            df, LSTMConfig(max_epochs=2, long_entry_threshold=0.0),
            initial_train_bars=500, refit_every=200,
        )
        allows = sum(1 for b in range(550, 650, 25) if gate.allow_entry(b))
        assert allows == len(range(550, 650, 25))
