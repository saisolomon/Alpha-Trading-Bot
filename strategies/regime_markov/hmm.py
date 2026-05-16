"""
Hidden Markov Model regime gate (Phase 2 of the Roan framework).

Where the observable Markov chain in markov.py classifies bars by a hand-
labelled formation return (a strictly lagging indicator -- proven on this
universe to never help), the HMM treats the regime as UNOBSERVED and INFERS
it from a vector of observable emissions per bar:

  emission_t = [log_return_t, realized_vol_t, cross_asset_signal_t, ...]

The Baum-Welch algorithm learns both the regime transition matrix AND the
per-regime emission distributions from data alone -- no hand labels. Then
at any bar the model produces a posterior distribution P(regime_t | emissions_{1..t})
which is RICHER than the observable label.

This module provides the HMM equivalent of MarkovRegimeGate with the same
interface (`allow_entry(bar_i) -> bool`) so it slots into MeanRevEngine
identically.

Two engineering safeguards essential to making HMM not overfit:

1. **Walk-forward training.** Fit the HMM on bars [0, train_end), then
   apply to bars [train_end, train_end + step). Re-fit every `refit_every`
   bars. Never use a bar to fit a model that's then asked about that bar.

2. **Multiple random initializations.** Baum-Welch is local-search.
   Different init seeds reach different local maxima. We run N inits and
   keep the model with highest log-likelihood.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# Try to import hmmlearn. Module is importable without it; gate creation fails.
try:
    from hmmlearn import hmm as _hmmlearn
    _HAVE_HMMLEARN = True
except ImportError:
    _HAVE_HMMLEARN = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HMMConfig:
    """Parameters for the Gaussian-emission HMM."""

    n_states: int = 3
    """Number of hidden regimes (typically 3 = bull/bear/sideways)."""

    vol_window: int = 20
    """Realized vol lookback (in bars)."""

    cross_window: int = 60
    """Cross-asset cumulative return lookback."""

    n_init: int = 5
    """Number of Baum-Welch initialisations; keep the highest-LL model."""

    n_iter: int = 200
    """Maximum Baum-Welch iterations per init."""

    initial_train_bars: int = 504
    """First fit uses this many bars (~2 years)."""

    refit_every: int = 63
    """Re-fit the model every N bars (~quarterly)."""

    covariance_type: str = "diag"
    """hmmlearn covariance_type. 'diag' is the sweet spot for stability."""

    seed_base: int = 42
    """Base seed for reproducibility; each init uses seed_base+i."""


@dataclass(frozen=True)
class HMMGateConfig:
    """Gate behaviour: when to deny entry based on the inferred posterior."""

    bear_state_threshold: float = 0.40
    """If P(bear-like regime) > this, deny entry. 'Bear-like' = the state
    with the most negative learned mean log return."""


# ---------------------------------------------------------------------------
# Feature engineering -- the emission vector
# ---------------------------------------------------------------------------


def build_emissions(
    prices_per_symbol: dict[str, pd.Series],
    target_symbol: str,
    config: HMMConfig,
) -> pd.DataFrame:
    """Construct the per-bar emission matrix for one symbol.

    Per Roan's article, the most useful features are STATIONARY signals
    that contain regime information:

      * own log return (mean shifts in regime change)
      * own realized vol (regime change usually shifts vol)
      * cross-asset cumulative return (risk-on/off shows in correlations)

    The cross-asset signal is the equal-weight mean of log returns across
    ALL OTHER symbols in the universe. This is the cheapest macro signal.

    Returns a DataFrame indexed like the target symbol's prices, columns
    [log_ret, realized_vol, cross_ret]. Warmup bars are NaN.
    """
    target_prices = prices_per_symbol[target_symbol]
    log_rets = np.log(target_prices).diff()

    rolling_vol = log_rets.rolling(config.vol_window).std()

    # Cross-asset signal: mean log return of other symbols over the
    # cross_window. Compute per-symbol then average.
    other_cumrets = []
    for sym, prices in prices_per_symbol.items():
        if sym == target_symbol:
            continue
        # Reindex to the target's index so the cumulative sum aligns.
        sym_log_rets = np.log(prices).diff().reindex(target_prices.index)
        other_cumrets.append(sym_log_rets.rolling(config.cross_window).sum())

    if other_cumrets:
        cross_signal = pd.concat(other_cumrets, axis=1).mean(axis=1)
    else:
        cross_signal = pd.Series(0.0, index=target_prices.index)

    return pd.DataFrame({
        "log_ret": log_rets,
        "realized_vol": rolling_vol,
        "cross_ret": cross_signal,
    }, index=target_prices.index)


# ---------------------------------------------------------------------------
# Best-of-N Baum-Welch
# ---------------------------------------------------------------------------


def fit_best_hmm(X: np.ndarray, config: HMMConfig):
    """Fit `n_init` independent HMMs on X and return the one with highest
    log-likelihood. Returns None if hmmlearn is not installed.

    X must be a numpy 2D array shape (n_bars, n_features) with NO NaN.
    """
    if not _HAVE_HMMLEARN:
        return None

    if X.shape[0] < config.n_states * 3:
        # Hopelessly under-determined; refuse to fit.
        return None

    best_model = None
    best_ll = -np.inf
    for i in range(config.n_init):
        try:
            model = _hmmlearn.GaussianHMM(
                n_components=config.n_states,
                covariance_type=config.covariance_type,
                n_iter=config.n_iter,
                random_state=config.seed_base + i,
                tol=1e-3,
            )
            # Suppress convergence warnings to keep CI logs clean.
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model.fit(X)
            ll = model.score(X)
            if ll > best_ll:
                best_ll = ll
                best_model = model
        except Exception:
            # Some seeds fail to converge or hit degenerate covariances.
            # Skip them; the best of N inits is what we want anyway.
            continue
    return best_model


def identify_bear_state(model, train_X: np.ndarray) -> int:
    """Identify which of the learned states is 'bear-like' = lowest mean
    log-return in the emission (feature column 0).

    Returns the integer state index (0 to n_states-1).
    """
    means = model.means_[:, 0]  # log_ret means per state
    return int(np.argmin(means))


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class HMMRegimeGate:
    """Walk-forward HMM regime gate.

    Maintains a fitted HMM that gets refit every `refit_every` bars. At each
    query bar, infers the posterior P(regime_t | emissions_{1..t}), looks at
    the probability of the bear-like state, and denies entry if that
    probability exceeds the gate threshold.

    Per-symbol -- each tradeable symbol gets its own HMM trained on its own
    emission stream (with the universe's other symbols feeding the cross-
    asset feature).
    """

    def __init__(
        self,
        prices_per_symbol: dict[str, pd.Series],
        target_symbol: str,
        config: HMMConfig,
        gate_config: HMMGateConfig,
    ) -> None:
        if not _HAVE_HMMLEARN:
            raise RuntimeError("hmmlearn not installed; cannot use HMMRegimeGate. "
                                "uv add hmmlearn")
        self._target = target_symbol
        self._config = config
        self._gcfg = gate_config

        # Precompute emissions once (no look-ahead in the values; the gate
        # only USES emissions[0..bar_i] when answering at bar_i).
        self._emissions_df = build_emissions(prices_per_symbol, target_symbol, config)

        # Cache: when we re-fit the model, we save (last_fit_bar, model,
        # bear_state) so subsequent queries can re-use it.
        self._cache: dict[int, tuple[object, int]] = {}

    def _fit_at(self, bar_i: int) -> Optional[tuple[object, int]]:
        """Return (model, bear_state_idx) trained on bars [0, bar_i].
        Returns None if we can't yet fit (insufficient data) or hmmlearn
        rejected all initialisations."""
        # Quantize bar_i to the nearest refit point so we don't refit every
        # bar (expensive). Refits happen at multiples of refit_every past
        # the initial_train_bars threshold.
        if bar_i < self._config.initial_train_bars:
            return None
        # The "effective" fit-bar: largest multiple of refit_every <= bar_i.
        step = self._config.refit_every
        first = self._config.initial_train_bars
        n_refits = (bar_i - first) // step
        fit_bar = first + n_refits * step
        if fit_bar in self._cache:
            return self._cache[fit_bar]

        # Build training matrix: emissions[0:fit_bar+1], drop NaN warmup rows.
        train_df = self._emissions_df.iloc[: fit_bar + 1].dropna()
        if len(train_df) < self._config.n_states * 3:
            return None

        X = train_df.to_numpy()
        model = fit_best_hmm(X, self._config)
        if model is None:
            return None
        bear_state = identify_bear_state(model, X)
        self._cache[fit_bar] = (model, bear_state)
        return model, bear_state

    def posterior_at(self, bar_i: int) -> Optional[np.ndarray]:
        """Posterior probability over hidden states given emissions[0..bar_i].

        Returns None if no model available at this bar (warmup).
        """
        fit = self._fit_at(bar_i)
        if fit is None:
            return None
        model, _bear = fit
        # Emissions up through bar_i; drop any NaN rows.
        obs_df = self._emissions_df.iloc[: bar_i + 1].dropna()
        if obs_df.empty:
            return None
        X = obs_df.to_numpy()
        try:
            # predict_proba returns shape (T, n_states). We want the last row.
            posteriors = model.predict_proba(X)
            return posteriors[-1]
        except Exception:
            return None

    def bear_state_index(self, bar_i: int) -> Optional[int]:
        """Which state index is currently classified as 'bear-like'."""
        fit = self._fit_at(bar_i)
        return None if fit is None else fit[1]

    def allow_entry(self, bar_i: int) -> bool:
        """Return True if entry is permitted at bar_i+1."""
        post = self.posterior_at(bar_i)
        bear = self.bear_state_index(bar_i)
        if post is None or bear is None:
            # Warmup -- be conservative, deny.
            return False
        # bool() cast: numpy comparisons return np.bool_, callers depend on
        # the Python bool type (e.g. `is True` checks in tests / engine code).
        return bool(post[bear] <= self._gcfg.bear_state_threshold)

    def gate_decision_reason(self, bar_i: int) -> str:
        post = self.posterior_at(bar_i)
        bear = self.bear_state_index(bar_i)
        if post is None or bear is None:
            return "warmup not satisfied / hmm not yet fit"
        bear_p = post[bear]
        return f"bear_state={bear}  P(bear|obs)={bear_p:.2f}  full={post.round(2).tolist()}"
