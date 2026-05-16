# Strategy Component: Markov Regime Gate

## What this is

NOT a standalone strategy — a **gate** that sits in front of the existing
Index MR strategy. Per Roan's article 1 (Markov Chains for high-probability
trades), we classify the current market regime into Bull / Bear / Sideways,
estimate the transition matrix from history, and forecast the probability of
each regime over the next N bars. The gate **suppresses MR entries when the
next-bar Bear probability exceeds a threshold** — exactly the 2019-2020
failure mode where the existing strategy whipsawed long into a regime shift.

## The problem this addresses

From `Memory.md 2026-05-11`, the 12-year walk-forward of Index MR:
> Worst year (2019-2020): Sharpe **−0.52**, return **−1.9%**, win rate
> 35.7%. Strategy gave whipsaw long entries in the pre-COVID + crash-onset
> period.

The MR strategy's vol regime filter (90th-percentile realized vol) DOES
catch obvious bear markets like 2022 (correct hibernation). But it MISSES
gradual regime transitions where vol stays moderate while the trend rolls
over — exactly 2019-Q4 through 2020-Q1.

A Markov regime model trained on past data classifies each bar by regime
**explicitly**. When the rolling transition matrix shows "from current
state, P(Bear next bar) > 0.4", we know we're in a transition zone and we
suppress new long entries.

## Mechanism — why a Markov chain captures this

Per Roan's article (and the source material from Asness, Moskowitz et al.):

1. **Markets have local dependence.** Today's regime is conditional on
   yesterday's, but not on what happened 100 days ago. The Markov
   property (memorylessness given current state) is a defensible
   approximation of how regime persistence actually works.

2. **Transition probabilities are estimable.** Maximum-likelihood
   estimator is just `count(i→j) / count(i→any)`. With 12y of D1 data
   (3000+ bars per symbol) and 3 states, each cell is estimated from
   hundreds of observations — well above the "≥30 per cell" rule of thumb.

3. **Multi-step forecasts via matrix power.** Chapman-Kolmogorov:
   `P(n)(i, j) = (P^n)[i, j]`. Compute the probability of being in any
   state n bars ahead in one matrix multiplication. Trivial.

4. **Stationary distribution as a sanity check.** Solve `π = πP` for
   the long-run regime proportions. If the bull/sideways/bear shares are
   wildly different from prior expectation (~50/30/20 on US equity
   indices), the model is misspecified or the sample is non-stationary.

## State definition

Three states, computed from a rolling formation-period return:

- `bull` = rolling 20-day return > +2%
- `bear` = rolling 20-day return < −2%
- `sideways` = everything in between

Thresholds are deliberately symmetric. Per Roan's article these are
typical defaults; in our parameter sweep we'll test `±20%` perturbations
(per CLAUDE.md sec.10 — parameter sensitivity).

## Transition matrix estimation

Strict walk-forward (no look-ahead):

1. At each evaluation bar `t`, slice past data `prices[t-lookback : t]`.
2. Label each bar in that slice with its regime.
3. Count transitions: `count[i][j] += 1` for each consecutive bar pair
   `(state_k, state_{k+1})` where `state_k = i` and `state_{k+1} = j`.
4. Row-normalize: `P_hat[i][j] = count[i][j] / row_sum(i)`.

The transition matrix is re-estimated every N bars (default: every bar, but
configurable for speed).

## Gate behavior

At the close of bar `t`:

1. Identify the current state `s_t` from the latest formation return.
2. Compute the 1-bar-ahead state distribution: `P_hat[s_t, :]`.
3. If `P_hat[s_t, BEAR] > bear_threshold` (default 0.40): **gate denies entry**.
4. Otherwise: **gate permits entry** (the MR strategy makes its own decision).

Note: this gate does NOT close existing positions. It only affects NEW
entries. Existing positions exit on the MR strategy's own stops/TPs.

## Pass criteria (Phase 1 specific)

The gate is worth keeping if, on the 12y walk-forward of Index MR:

1. **2019-2020 OOS Sharpe lifts** from −0.52 toward zero or positive.
2. **Other OOS years not significantly degraded** (worst-case ≤ −0.20).
3. **Mean OOS Sharpe ≥ 0.49** (current baseline).
4. **All windows still FTMO PASS**.
5. **Trade count drops modestly but not catastrophically** (gate is
   suppressing some entries; if it suppresses too many we lose the edge).

If 1 and 3 both pass, the gate is a keeper.
If only 1 passes (it helps 2019-2020 but hurts the average), it's a
regime-overfit and we reject it.
If neither passes, the regime gating idea doesn't help on this universe.

## Known weaknesses

1. **The Markov property is an approximation.** Real regime persistence has
   longer-range dependence. We can partially address by expanding state
   space to include duration (Bull-just-started vs Bull-30-days-in), but
   this multiplies states and erodes the per-cell sample size.

2. **Time homogeneity is violated.** Transition probabilities in 2008 are
   different from 2021. Rolling-window estimation (default 504 bars =
   ~2 years) is the standard mitigation. Shorter windows adapt faster
   but produce noisier estimates.

3. **Three states is a simplification.** Could use more (e.g. high-vol-bull
   vs low-vol-bull) but each new state divides the per-cell sample roughly
   3x. For 12y of D1 data, 3 states is the sweet spot.

4. **Doesn't see latent regimes.** The current implementation is the
   observable Markov chain. Phase 2 of the Roan framework upgrades to HMM
   where the regime is inferred from observable returns + vol + spreads.
   That comes after we prove the simpler observable model is worth the
   gating infrastructure.

## References

- Roan (@RohOnChain), "How Hedge Funds Use Markov Chains to Find High-
  Probability Trades" — the framework this hypothesis adapts.
- Asness, Moskowitz, Pedersen (2013), "Value and Momentum Everywhere" —
  regime-switching evidence in cross-asset returns.
- Hamilton (1989), "A New Approach to the Economic Analysis of Nonstationary
  Time Series and the Business Cycle" — the foundational Markov-switching
  regression paper for macro / financial time series.
