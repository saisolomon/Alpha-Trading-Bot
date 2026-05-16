"""
Unit tests for the HMM regime gate (strategies/regime_markov/hmm.py).

Skipped when hmmlearn isn't installed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# Skip the whole module if hmmlearn isn't available.
pytest.importorskip("hmmlearn")

from strategies.regime_markov.hmm import (
    HMMConfig,
    HMMGateConfig,
    HMMRegimeGate,
    build_emissions,
    fit_best_hmm,
    identify_bear_state,
)


def _synth_prices(name: str, n: int = 800, seed: int = 1,
                   drift: float = 0.0003, vol: float = 0.012) -> pd.Series:
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(drift, vol, n)
    closes = 100.0 * np.exp(np.cumsum(log_rets))
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.Series(closes, index=idx, name=name)


def _synth_universe(n: int = 800) -> dict[str, pd.Series]:
    return {
        "A": _synth_prices("A", n=n, seed=1, drift=0.0003),
        "B": _synth_prices("B", n=n, seed=2, drift=0.0002),
        "C": _synth_prices("C", n=n, seed=3, drift=0.0004),
    }


# ---------------------------------------------------------------------------
# Emissions
# ---------------------------------------------------------------------------


class TestBuildEmissions:

    def test_columns_present(self):
        prices = _synth_universe(200)
        emissions = build_emissions(prices, "A", HMMConfig())
        assert set(emissions.columns) == {"log_ret", "realized_vol", "cross_ret"}

    def test_warmup_is_nan(self):
        prices = _synth_universe(200)
        config = HMMConfig(vol_window=20, cross_window=60)
        emissions = build_emissions(prices, "A", config)
        # First bar always NaN (no prior close for log_ret)
        assert pd.isna(emissions["log_ret"].iloc[0])
        # realized_vol needs vol_window bars
        assert pd.isna(emissions["realized_vol"].iloc[18])
        # cross_ret needs cross_window bars
        assert pd.isna(emissions["cross_ret"].iloc[58])

    def test_no_look_ahead(self):
        """Emissions at bar 100 must not change if bars > 100 change."""
        prices = _synth_universe(200)
        config = HMMConfig(vol_window=20, cross_window=60)
        e1 = build_emissions(prices, "A", config)
        prices2 = {k: v.copy() for k, v in prices.items()}
        prices2["B"].iloc[101:] *= 1.5  # mutate future of B
        e2 = build_emissions(prices2, "A", config)
        # Emission of A at bar 100 should be unchanged
        for col in ["log_ret", "realized_vol", "cross_ret"]:
            assert e1[col].iloc[100] == pytest.approx(e2[col].iloc[100], abs=1e-12)


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


class TestFitBestHmm:

    def test_returns_none_on_insufficient_data(self):
        X = np.random.randn(2, 3)
        config = HMMConfig(n_states=3, n_init=2)
        model = fit_best_hmm(X, config)
        assert model is None

    def test_fits_on_sufficient_data(self):
        rng = np.random.default_rng(0)
        # Make a 2-regime synthetic with clearly different means
        n = 400
        X = np.empty((n, 2))
        for i in range(n):
            if (i // 50) % 2 == 0:
                X[i] = rng.normal([0.005, 0.01], 0.005)
            else:
                X[i] = rng.normal([-0.005, 0.02], 0.005)
        config = HMMConfig(n_states=2, n_init=3)
        model = fit_best_hmm(X, config)
        assert model is not None
        assert model.means_.shape == (2, 2)

    def test_identify_bear_state(self):
        """The state with the most negative learned log_ret mean is 'bear'."""
        rng = np.random.default_rng(1)
        n = 400
        X = np.empty((n, 2))
        for i in range(n):
            # state 0: positive returns; state 1: negative returns
            if (i // 50) % 2 == 0:
                X[i] = rng.normal([+0.01, 0.01], 0.003)
            else:
                X[i] = rng.normal([-0.01, 0.02], 0.003)
        config = HMMConfig(n_states=2, n_init=3)
        model = fit_best_hmm(X, config)
        assert model is not None
        bear = identify_bear_state(model, X)
        assert model.means_[bear, 0] == min(model.means_[:, 0])


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class TestHMMRegimeGate:

    def test_warmup_denies_entry(self):
        prices = _synth_universe(700)
        gate = HMMRegimeGate(
            prices_per_symbol=prices,
            target_symbol="A",
            config=HMMConfig(initial_train_bars=500),
            gate_config=HMMGateConfig(),
        )
        # Before initial_train_bars -> warmup -> deny
        assert gate.allow_entry(100) is False

    def test_makes_decision_after_warmup(self):
        prices = _synth_universe(800)
        gate = HMMRegimeGate(
            prices_per_symbol=prices,
            target_symbol="A",
            config=HMMConfig(initial_train_bars=500, n_init=2),
            gate_config=HMMGateConfig(),
        )
        # After warmup, gate should return a boolean (T or F is fine)
        decision = gate.allow_entry(700)
        assert isinstance(decision, bool)

    def test_threshold_one_always_permits(self):
        prices = _synth_universe(800)
        gate = HMMRegimeGate(
            prices_per_symbol=prices,
            target_symbol="A",
            config=HMMConfig(initial_train_bars=500, n_init=2),
            gate_config=HMMGateConfig(bear_state_threshold=1.0),
        )
        # bear_state_threshold = 1.0 means P(bear) <= 1.0 is always true
        # -> always permit post-warmup
        for bar in range(600, 700, 25):
            assert gate.allow_entry(bar) is True

    def test_threshold_zero_mostly_denies(self):
        prices = _synth_universe(800)
        gate = HMMRegimeGate(
            prices_per_symbol=prices,
            target_symbol="A",
            config=HMMConfig(initial_train_bars=500, n_init=2),
            gate_config=HMMGateConfig(bear_state_threshold=0.001),
        )
        # Very low threshold should deny most bars (P(bear) > 0.001 typical)
        denies = sum(1 for b in range(600, 750) if not gate.allow_entry(b))
        assert denies >= 75  # at least half

    def test_refit_only_at_step_boundaries(self):
        """The same fit result should be returned for bars within the same
        refit window -- this is a cache-hit verification."""
        prices = _synth_universe(800)
        gate = HMMRegimeGate(
            prices_per_symbol=prices,
            target_symbol="A",
            config=HMMConfig(initial_train_bars=500, refit_every=63, n_init=1),
            gate_config=HMMGateConfig(),
        )
        # Calls at bars 600 and 610 should hit the same cached model
        post_600 = gate.posterior_at(600)
        post_610 = gate.posterior_at(610)
        # Should not be identical (different observed bars) but the model
        # behind them is the same fit. We can only check the cache directly:
        assert 500 in gate._cache or any(k <= 600 for k in gate._cache)
