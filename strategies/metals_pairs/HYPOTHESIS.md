# Strategy Hypothesis: Gold-Silver Cointegration Spread Mean-Reversion

## One-Line Hypothesis

The log-price spread between gold (XAUUSD) and silver (XAGUSD) is
**cointegrated** — meaning the two prices share a stable long-run
equilibrium relationship and the spread is mean-reverting. When the
spread deviates by 2+ standard deviations from its rolling mean, we
profit by betting the spread reverts: long the cheap leg, short the
expensive leg, with leg sizes chosen so the dollar exposures balance
to ≈ 0.

This is **structurally market-neutral** — the strategy has no net
directional exposure to "metals up" or "metals down". That's exactly
what we need as a diversifier against the long-only Index MR strategy.

## Why This Edge Exists

### The Economic Mechanism

1. **Shared fundamental drivers.** Gold and silver are both monetary
   metals with overlapping demand structure (jewelry, investment, store
   of value, partial industrial). When real-rate expectations or USD
   strength move one, they typically move the other in the same
   direction. Brennan-Schwartz (1985) "Evaluating Natural Resource
   Investments" formalises the convenience-yield arbitrage that drives
   this co-movement.

2. **Heterogeneous short-term flows.** While the long-run relationship
   is stable, short-term flows differ. Gold has dominant ETF flows and
   central-bank buying; silver has ~50% industrial demand (solar,
   electronics, electrical) creating noisier short-term price action.
   These idiosyncratic flows TEMPORARILY widen the spread; over weeks-to-
   months the cointegration force pulls it back.

3. **Arbitrage discipline.** Real arbitrageurs (hedge funds, family
   offices, refiners running spread books) trade this exact pair. Their
   activity IS what enforces cointegration. The strategy is essentially
   joining their flow at extreme deviations.

### Academic Support

- **Brennan & Schwartz (1985), JFE** — convenience yield + cointegration
  in commodity prices. The foundational reference.
- **Engle & Granger (1987), Econometrica** — formal cointegration test
  (the one we use in scripts/pairs_cointegration_test.py).
- **Gatev, Goetzmann, Rouwenhorst (2006), RFS** — "Pairs Trading:
  Performance of a Relative-Value Arbitrage Rule." Documents pairs
  trading edge across 40 years of equity data; the methodology
  generalises cleanly to commodity pairs.
- **Vidyamurthy (2004), "Pairs Trading: Quantitative Methods and
  Analysis"** — the practitioner reference for cointegration-based
  pairs trading construction.

### Why This Pair Specifically

From scripts/pairs_cointegration_test.py on 12y of cached D1 data:

| Pair | ADF p-value | Half-life | Beta | Verdict |
|---|---|---|---|---|
| **XAUUSD-XAGUSD** | **0.027** | **123 bars** | **0.92** | COINTEGRATED |
| XAGUSD-XPTUSD | 0.044 | 122 bars | 1.62 | cointegrated |
| XAUUSD-XPTUSD | 0.112 | 212 bars | 1.28 | borderline |

Gold-silver has the cleanest cointegration: lowest p-value (most
statistically significant), beta close to 1 (interpretable as roughly
1:1 dollar exposure), half-life of ~6 months (long enough that costs
don't dominate, short enough to trade within a Challenge window).

Silver-platinum is also cointegrated but with beta=1.62 it's a thinner
relationship; platinum has less liquidity on this broker; skip.

## Signal Construction

**Spread definition (the cointegrating relationship):**

  spread_t = log(P_xauusd_t) − β · log(P_xagusd_t) − α

where β and α are estimated by OLS regression on the **rolling**
window (504 bars = ~2 years) ending at bar T. NEVER fit on the full
sample — that would leak future information about the equilibrium.

**z-score (the trade signal):**

  z_t = (spread_t − rolling_mean(spread, 252)) / rolling_std(spread, 252)

**Entry conditions:**

- **Long-spread:** z_t < −entry_z (e.g. z < −2.0). Means gold is cheap
  relative to silver. Action: long gold, short silver (sized so
  dollar exposures cancel).
- **Short-spread:** z_t > +entry_z. Means gold is expensive relative
  to silver. Action: short gold, long silver.

**Exit conditions:**

- **Mean-reversion exit:** |z| < exit_z (e.g. 0.5). Reversion played
  out; book the profit.
- **Time stop:** holding > max_hold_bars (e.g. 60 D1 bars ≈ ½ the
  half-life). Avoids dead trades that never revert.
- **Cointegration-broken stop:** |z| > catastrophic_z (e.g. 4.0).
  The spread blew through our entry by another 2σ — the cointegrating
  relationship may have broken. Exit at a loss.

## Position Sizing (the critical detail)

For TRUE market-neutrality, dollar exposures must cancel:

  $_xauusd = lots_xauusd · contract_size_xauusd · price_xauusd
  $_xagusd = lots_xagusd · contract_size_xagusd · price_xagusd

We want: $_xauusd = β · $_xagusd  (the cointegrating relationship).

Given a risk budget R (per-trade USD risk) and our ATR-based stop on
the spread:

  spread_stop_distance = atr_spread · atr_mult
  spread_risk_per_unit = (some function of leg sizes)
  lots_xauusd = R · w_xauusd / (price · stop_distance · tick_value)

The leg-sizing math is tricky enough that we'll implement it carefully
in `metals_pairs/sizing.py`.

## Pass Criteria

Before the strategy can be deployed:

1. **Sharpe ≥ 0.5 in walk-forward OOS** averaged across windows.
2. **Max DD ≤ 8%** (slightly tighter than Index MR's 10% target since
   pairs trades can take longer to revert).
3. **FTMO sim PASS** on all OOS windows.
4. **Correlation with Index MR ≤ 0.3** on daily equity changes. THE
   diversification requirement — if the two strategies move together,
   the pair adds no portfolio value.
5. **All trades respect both legs' position limits.** Both legs must
   have available margin AND pass the OCaml headroom check.

## Known Weaknesses

1. **Cointegration breakdown.** If gold and silver decouple
   structurally (e.g. industrial silver demand collapses, retail gold
   buying surges in a crisis), the spread won't revert. The
   catastrophic-z stop is the only protection — it may fill far
   below entry on a true regime break.

2. **Long holding period.** With half-life ~123 bars (~6 months on
   D1), individual trades can sit open for 1-3 months. This:
     - exposes positions to weekend gaps,
     - accumulates swap costs (gold/silver have non-trivial financing),
     - ties up margin.

3. **Correlated stop-outs.** If a major risk-off event causes
   simultaneous flight to gold (long spread) AND fly-to-USD selling
   of silver (short spread), our long-spread bet wins. But the
   inverse scenario — risk-on equity rally with silver outperforming
   gold — produces simultaneous losses on multiple historical
   open trades.

4. **Two-leg execution.** Every entry and exit is TWO orders.
   Doubles the spread-cost and slippage burden vs. single-leg trades.

5. **Cointegration p-value is 0.027, not 0.001.** This is "evidence
   of cointegration" not "proof of cointegration." The relationship
   could weaken over time. Re-test cointegration during each
   walk-forward refit and PAUSE the strategy if p-value rises above
   0.10.

## Regime Conditions

**Active:**
- Rolling cointegration test (every 63 bars) still produces p < 0.10.
- Both legs' brokers report normal spreads (skip if either is unusually
  wide).
- FTMO headroom > 1% of both lines.

**Paused / sized down:**
- Rolling cointegration p > 0.10 → no new entries until it tightens.
- Rolling 6-month strategy Sharpe < −0.5 → halt until manual review.
- Friday cut-off (per FTMO standard accounts) — flat both legs.
