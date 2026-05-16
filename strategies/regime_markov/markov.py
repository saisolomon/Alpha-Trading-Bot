"""
Observable Markov chain regime model.

Three states (Bull / Bear / Sideways) defined by rolling formation-period
return thresholds. Transition matrix estimated by maximum likelihood from a
rolling window of past data. Strictly walk-forward -- the transition matrix
at bar T uses only bars [T-lookback : T].

Used as a GATE for the existing Index MR strategy, not as a standalone
trade signal. See HYPOTHESIS.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# State definitions
# ---------------------------------------------------------------------------


class Regime(IntEnum):
    BULL = 0
    BEAR = 1
    SIDEWAYS = 2


N_STATES = 3
REGIME_NAMES = ["Bull", "Bear", "Sideways"]


@dataclass(frozen=True)
class MarkovConfig:
    """Parameters for the Markov regime model."""

    formation_bars: int = 20           # rolling-return window for state labelling
    bull_threshold: float = 0.02       # formation_return > this  -> Bull
    bear_threshold: float = -0.02      # formation_return < this  -> Bear
    estimation_lookback: int = 504     # bars used to estimate the transition matrix
    min_observations_per_cell: int = 30  # warn if any cell has fewer observations

    @classmethod
    def from_dict(cls, d: dict) -> "MarkovConfig":
        return cls(
            formation_bars=d.get("formation_bars", 20),
            bull_threshold=d.get("bull_threshold", 0.02),
            bear_threshold=d.get("bear_threshold", -0.02),
            estimation_lookback=d.get("estimation_lookback", 504),
            min_observations_per_cell=d.get("min_observations_per_cell", 30),
        )


# ---------------------------------------------------------------------------
# State labelling
# ---------------------------------------------------------------------------


def label_states(returns: pd.Series, config: MarkovConfig) -> pd.Series:
    """Label each bar with its Markov state based on the formation-period
    cumulative return.

    Returns a pandas Series of int values (Regime IntEnum casts). The first
    `formation_bars` values are NaN (warmup).
    """
    rolling_ret = returns.rolling(config.formation_bars).sum()
    states = pd.Series(np.nan, index=returns.index, dtype="float64")
    states.loc[rolling_ret > config.bull_threshold] = float(Regime.BULL)
    states.loc[rolling_ret < config.bear_threshold] = float(Regime.BEAR)
    middle = (rolling_ret >= config.bear_threshold) & (rolling_ret <= config.bull_threshold)
    states.loc[middle] = float(Regime.SIDEWAYS)
    return states


# ---------------------------------------------------------------------------
# Transition matrix estimation
# ---------------------------------------------------------------------------


def estimate_transition_matrix(
    states: pd.Series,
    n_states: int = N_STATES,
) -> tuple[np.ndarray, np.ndarray]:
    """Maximum-likelihood transition matrix from an observed state sequence.

    Returns
    -------
    P : (n_states, n_states) ndarray
        Row-normalized transition matrix. Row i = P(j | i).
        If a row has zero observations, P[i, :] defaults to uniform 1/n_states.
    counts : (n_states, n_states) ndarray
        Raw transition counts (for sanity-checking against the
        min_observations_per_cell threshold).
    """
    counts = np.zeros((n_states, n_states), dtype=np.int64)
    arr = states.dropna().to_numpy().astype(np.int64)
    if len(arr) < 2:
        # Insufficient data -- return uniform prior so the gate can't crash.
        return np.full((n_states, n_states), 1.0 / n_states), counts
    for i, j in zip(arr[:-1], arr[1:]):
        if 0 <= i < n_states and 0 <= j < n_states:
            counts[i, j] += 1
    P = np.zeros_like(counts, dtype=np.float64)
    for i in range(n_states):
        s = counts[i].sum()
        if s > 0:
            P[i, :] = counts[i] / s
        else:
            P[i, :] = 1.0 / n_states
    return P, counts


# ---------------------------------------------------------------------------
# Stationary distribution (sanity check)
# ---------------------------------------------------------------------------


def stationary_distribution(P: np.ndarray) -> np.ndarray:
    """Solve pi = pi @ P for the long-run regime proportions.

    Reduces to solving (P.T - I) pi = 0 with the constraint sum(pi) = 1.
    """
    n = P.shape[0]
    A = (P.T - np.eye(n)).copy()
    A[-1] = 1.0
    b = np.zeros(n)
    b[-1] = 1.0
    try:
        return np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        return np.full(n, 1.0 / n)


# ---------------------------------------------------------------------------
# Forward step (re-export from libquant when available)
# ---------------------------------------------------------------------------


try:
    import quantlib as _qlib
    _HAVE_QUANTLIB = True
except ImportError:
    _HAVE_QUANTLIB = False


def forward_step(state_prob: np.ndarray, P: np.ndarray) -> np.ndarray:
    """One Markov forward step: new[j] = sum_i state[i] * P[i, j].

    Uses the C++ libquant implementation when available (single-source-of-truth
    with the live MQL5 EA), falls back to numpy otherwise.
    """
    state_arr = np.asarray(state_prob, dtype=np.float64)
    P_arr = np.asarray(P, dtype=np.float64)
    n = state_arr.shape[0]
    assert P_arr.shape == (n, n), "transition matrix must be n_states x n_states"
    if _HAVE_QUANTLIB:
        out = _qlib.markov_forward_step(state_arr.tolist(), P_arr.flatten().tolist())
        return np.asarray(out)
    return state_arr @ P_arr


def forward_n_steps(state_prob: np.ndarray, P: np.ndarray, n_steps: int) -> np.ndarray:
    """Apply n_steps successive forward steps."""
    if _HAVE_QUANTLIB:
        state_arr = np.asarray(state_prob, dtype=np.float64)
        P_arr = np.asarray(P, dtype=np.float64)
        out = _qlib.markov_forward_n_steps(
            state_arr.tolist(), P_arr.flatten().tolist(), n_steps
        )
        return np.asarray(out)
    current = np.asarray(state_prob, dtype=np.float64)
    P_arr = np.asarray(P, dtype=np.float64)
    for _ in range(n_steps):
        current = current @ P_arr
    return current


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateConfig:
    """Configuration for the Markov regime gate."""

    bear_threshold: float = 0.40
    """If 1-bar-ahead P(BEAR) > this, the gate denies entry."""

    use_quantlib: bool = True
    """Use C++ libquant for the forward step when available."""


class MarkovRegimeGate:
    """Stateful regime gate.

    Maintains a rolling transition matrix, re-estimating it from the trailing
    `estimation_lookback` bars. Provides `allow_entry(bar_i)` which the
    strategy calls before opening a long position.
    """

    def __init__(
        self,
        prices: pd.Series,
        markov_config: MarkovConfig,
        gate_config: GateConfig,
    ) -> None:
        self._prices = prices
        self._returns = prices.pct_change()
        self._mcfg = markov_config
        self._gcfg = gate_config
        # Label every bar once -- it only uses past bars within the formation
        # window, so no look-ahead at label time. (The gate's transition-matrix
        # estimation IS strictly walk-forward.)
        self._states = label_states(self._returns, markov_config)

    @property
    def states(self) -> pd.Series:
        """Read-only access to the regime label series."""
        return self._states

    def current_state(self, bar_i: int) -> Optional[int]:
        """Return the regime at bar_i, or None if the warmup window is not
        yet satisfied."""
        if bar_i < 0 or bar_i >= len(self._states):
            return None
        s = self._states.iloc[bar_i]
        if pd.isna(s):
            return None
        return int(s)

    def transition_matrix(self, bar_i: int) -> tuple[np.ndarray, np.ndarray]:
        """Estimate the transition matrix from the trailing
        estimation_lookback bars ending at bar_i (inclusive of bar_i).

        Strictly walk-forward: uses only bars in [bar_i - lookback, bar_i].
        """
        lo = max(0, bar_i - self._mcfg.estimation_lookback + 1)
        hi = bar_i + 1  # inclusive of bar_i
        slice_states = self._states.iloc[lo:hi]
        return estimate_transition_matrix(slice_states)

    def next_bar_regime_probs(self, bar_i: int) -> Optional[np.ndarray]:
        """One-bar-ahead probability vector for each regime, given the
        current state at bar_i. None if state at bar_i is not yet defined."""
        s = self.current_state(bar_i)
        if s is None:
            return None
        P, _counts = self.transition_matrix(bar_i)
        # state_prob is a one-hot at the current state
        one_hot = np.zeros(N_STATES)
        one_hot[s] = 1.0
        if self._gcfg.use_quantlib:
            return forward_step(one_hot, P)
        return one_hot @ P

    def allow_entry(self, bar_i: int) -> bool:
        """The actual gate: returns True if entry is permitted at bar_i+1
        open, False if the gate is blocking it."""
        probs = self.next_bar_regime_probs(bar_i)
        if probs is None:
            # Insufficient history -- be conservative, deny entry
            return False
        return probs[Regime.BEAR] <= self._gcfg.bear_threshold

    def gate_decision_reason(self, bar_i: int) -> str:
        """Human-readable diagnostic for the gate's decision at bar_i."""
        s = self.current_state(bar_i)
        if s is None:
            return "warmup not satisfied"
        probs = self.next_bar_regime_probs(bar_i)
        if probs is None:
            return "no transition matrix"
        return (f"state={REGIME_NAMES[s]}, "
                f"P(next)=[bull {probs[Regime.BULL]:.2f}, "
                f"bear {probs[Regime.BEAR]:.2f}, "
                f"sideways {probs[Regime.SIDEWAYS]:.2f}]")
