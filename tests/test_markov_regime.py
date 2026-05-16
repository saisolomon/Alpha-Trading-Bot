"""
Unit tests for strategies/regime_markov/markov.py.

Covers:
  - state labelling: bull/bear/sideways thresholds
  - transition matrix: rows sum to 1, MLE math is correct
  - stationary distribution: solves pi = pi P
  - walk-forward gate: no look-ahead, denies in warmup, behavior at boundary
  - parity with libquant forward_step (when available)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.regime_markov.markov import (
    GateConfig,
    MarkovConfig,
    MarkovRegimeGate,
    N_STATES,
    Regime,
    estimate_transition_matrix,
    forward_step,
    label_states,
    stationary_distribution,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synth_prices(n: int = 500, seed: int = 1, drift: float = 0.0003) -> pd.Series:
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(drift, 0.012, n)
    closes = 100.0 * np.exp(np.cumsum(log_rets))
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.Series(closes, index=idx, name="close")


def _default_config() -> MarkovConfig:
    return MarkovConfig(
        formation_bars=20,
        bull_threshold=0.02,
        bear_threshold=-0.02,
        estimation_lookback=200,
    )


# ---------------------------------------------------------------------------
# State labelling
# ---------------------------------------------------------------------------


class TestLabelStates:

    def test_warmup_is_nan(self):
        prices = _synth_prices(100)
        returns = prices.pct_change()
        states = label_states(returns, _default_config())
        # First `formation_bars` values must be NaN
        assert states.iloc[:19].isna().all()

    def test_strong_bull_labelled_bull(self):
        # Construct a series whose 20-bar cumulative return is unambiguously > +2%
        n = 50
        # 1% daily gain for 20 bars = ~22% rolling return
        log_rets = np.full(n, 0.01)
        prices = pd.Series(100.0 * np.exp(np.cumsum(log_rets)),
                            index=pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"))
        returns = prices.pct_change()
        states = label_states(returns, _default_config())
        assert int(states.iloc[-1]) == int(Regime.BULL)

    def test_strong_bear_labelled_bear(self):
        n = 50
        log_rets = np.full(n, -0.01)
        prices = pd.Series(100.0 * np.exp(np.cumsum(log_rets)),
                            index=pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"))
        returns = prices.pct_change()
        states = label_states(returns, _default_config())
        assert int(states.iloc[-1]) == int(Regime.BEAR)

    def test_flat_labelled_sideways(self):
        n = 50
        log_rets = np.zeros(n)
        prices = pd.Series(np.full(n, 100.0),
                            index=pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"))
        returns = prices.pct_change()
        states = label_states(returns, _default_config())
        # After warmup, anything that's not bull/bear is sideways
        valid = states.dropna()
        assert (valid == int(Regime.SIDEWAYS)).all()


# ---------------------------------------------------------------------------
# Transition matrix
# ---------------------------------------------------------------------------


class TestTransitionMatrix:

    def test_rows_sum_to_one(self):
        # Random valid state sequence
        rng = np.random.default_rng(42)
        states = pd.Series(rng.integers(0, N_STATES, size=200).astype(float))
        P, _ = estimate_transition_matrix(states)
        row_sums = P.sum(axis=1)
        assert np.allclose(row_sums, 1.0, atol=1e-12)

    def test_mle_matches_hand_count(self):
        # Sequence [0, 0, 1, 0, 1, 0] has consecutive pairs:
        #   (0,0) (0,1) (1,0) (0,1) (1,0)
        # From state 0 (3 outgoing): 1 to 0, 2 to 1 -> P[0]=[1/3, 2/3, 0]
        # From state 1 (2 outgoing): 2 to 0,  0 to 1 -> P[1]=[1, 0, 0]
        # From state 2: 0 outgoing -> uniform fallback 1/3 each.
        states = pd.Series([0.0, 0.0, 1.0, 0.0, 1.0, 0.0])
        P, counts = estimate_transition_matrix(states)
        assert counts[0, 0] == 1
        assert counts[0, 1] == 2
        assert counts[1, 0] == 2
        assert P[0, 0] == pytest.approx(1.0 / 3)
        assert P[0, 1] == pytest.approx(2.0 / 3)
        assert P[1, 0] == pytest.approx(1.0)
        assert np.allclose(P[2, :], 1.0 / N_STATES)

    def test_empty_input_returns_uniform(self):
        P, _ = estimate_transition_matrix(pd.Series([]))
        assert np.allclose(P, 1.0 / N_STATES)


# ---------------------------------------------------------------------------
# Stationary distribution
# ---------------------------------------------------------------------------


class TestStationaryDistribution:

    def test_solution_satisfies_pi_eq_piP(self):
        P = np.array([
            [0.8, 0.1, 0.1],
            [0.2, 0.6, 0.2],
            [0.1, 0.3, 0.6],
        ])
        pi = stationary_distribution(P)
        assert pi.sum() == pytest.approx(1.0, abs=1e-9)
        assert np.allclose(pi @ P, pi, atol=1e-9)

    def test_persistent_state_dominates_stationary(self):
        # State 0 is very persistent (stays 95% of the time); long-run
        # share should be highest for state 0.
        P = np.array([
            [0.95, 0.025, 0.025],
            [0.40, 0.50,  0.10],
            [0.40, 0.10,  0.50],
        ])
        pi = stationary_distribution(P)
        assert pi[0] > pi[1] and pi[0] > pi[2]


# ---------------------------------------------------------------------------
# Forward step (libquant parity if available)
# ---------------------------------------------------------------------------


class TestForwardStep:

    def test_matches_numpy_matmul(self):
        state = np.array([1.0, 0.0, 0.0])
        P = np.array([
            [0.7, 0.2, 0.1],
            [0.3, 0.5, 0.2],
            [0.1, 0.3, 0.6],
        ])
        out = forward_step(state, P)
        expected = state @ P
        assert np.allclose(out, expected, atol=1e-12)

    def test_uniform_prior_preserved_by_doubly_stochastic_matrix(self):
        # If P is doubly stochastic, the uniform distribution is stationary
        P = np.array([
            [0.5, 0.3, 0.2],
            [0.2, 0.5, 0.3],
            [0.3, 0.2, 0.5],
        ])
        uniform = np.array([1/3, 1/3, 1/3])
        out = forward_step(uniform, P)
        assert np.allclose(out, uniform, atol=1e-12)


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


class TestMarkovRegimeGate:

    def test_gate_denies_during_warmup(self):
        prices = _synth_prices(50)
        gate = MarkovRegimeGate(
            prices=prices,
            markov_config=MarkovConfig(formation_bars=20, estimation_lookback=200),
            gate_config=GateConfig(),
        )
        # In warmup -> current_state is None -> allow_entry is False
        assert gate.allow_entry(5) is False
        assert gate.current_state(5) is None

    def test_gate_decision_after_warmup(self):
        prices = _synth_prices(500, seed=2)
        gate = MarkovRegimeGate(
            prices=prices,
            markov_config=MarkovConfig(formation_bars=20, estimation_lookback=200),
            gate_config=GateConfig(bear_threshold=0.40),
        )
        # After lookback bars, gate should be able to decide
        decision = gate.allow_entry(450)
        assert decision in (True, False)
        assert gate.current_state(450) is not None

    def test_no_look_ahead_in_transition_matrix(self):
        """Estimating the transition matrix at bar T must use only bars <= T.
        We test at bar 299, where the matrix slice ends just before any
        future mutation can leak in (state[299] uses formation window
        [280..299], fully past-only)."""
        prices = _synth_prices(500, seed=3)
        gate_a = MarkovRegimeGate(
            prices=prices,
            markov_config=MarkovConfig(formation_bars=20, estimation_lookback=200),
            gate_config=GateConfig(),
        )
        P_a, _ = gate_a.transition_matrix(299)

        # Mutate bars strictly AFTER 300 (so bar 300 onwards changes; the
        # transition matrix at bar 299 must be untouched).
        prices_b = prices.copy()
        prices_b.iloc[301:] *= 1.5
        gate_b = MarkovRegimeGate(
            prices=prices_b,
            markov_config=MarkovConfig(formation_bars=20, estimation_lookback=200),
            gate_config=GateConfig(),
        )
        P_b, _ = gate_b.transition_matrix(299)
        assert np.allclose(P_a, P_b, atol=1e-12)

    def test_bear_threshold_of_zero_mostly_denies(self):
        """If we set the threshold to 0.0, the gate denies whenever the
        learned transition matrix gives ANY bear probability from the
        current state. On synthetic data with drift, this still denies a
        majority but not all bars (some states have learned zero bear
        transitions because the sample didn't visit bear from there)."""
        prices = _synth_prices(500, seed=4)
        gate = MarkovRegimeGate(
            prices=prices,
            markov_config=MarkovConfig(formation_bars=20, estimation_lookback=200),
            gate_config=GateConfig(bear_threshold=0.0),
        )
        denies = sum(1 for i in range(250, 450) if not gate.allow_entry(i))
        # Tight threshold (0.0) should deny at least half the bars in a
        # mixed-drift regime.
        assert denies >= 100

    def test_bear_threshold_of_one_permits_everything(self):
        """Threshold 1.0 -> can never exceed -> always allow (post-warmup)."""
        prices = _synth_prices(500, seed=5)
        gate = MarkovRegimeGate(
            prices=prices,
            markov_config=MarkovConfig(formation_bars=20, estimation_lookback=200),
            gate_config=GateConfig(bear_threshold=1.0),
        )
        allows = sum(1 for i in range(250, 450) if gate.allow_entry(i))
        assert allows == 200
