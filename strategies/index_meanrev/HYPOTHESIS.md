# Strategy Hypothesis: Short-Horizon Index Mean-Reversion (Long-Only)

## One-Line Hypothesis

After a 5–20 day **drawdown** large enough to be in the tail of the historical return
distribution (z < −1.5), equity index CFD prices systematically bounce back over the next 1–10
days. The edge is captured by **buying deep dips** on major equity indices, with tight stops to
bound the case where the drawdown continues into a new bear regime.

This is the **long-only side** of short-horizon mean-reversion. The original symmetric
hypothesis (also short large rallies) was empirically rejected on 2026-05-11: the decile bucket
test on the same 4-index universe found that big rallies *continue rallying* (top-decile
forward returns are positive on 3/4 symbols, opposite to mean-reversion expectation). The
asymmetry is consistent with the asymmetric-institutional-flow mechanism in this doc — most
equity capital is long-only, so dips attract reversion flow but rallies have no equivalent
fade pressure.

---

## Why This Edge Exists

### The Economic Mechanism

1. **Overreaction to short-horizon news.** Lehmann (1990) — "Fads, Martingales and Market
   Efficiency" — and Jegadeesh (1990) — "Evidence of Predictable Behavior of Security Returns"
   — established short-term reversal as a robust feature of equity returns. The mechanism is
   excess price-pressure from forced-flow trading: stop-loss triggers, margin calls, vol-target
   de-risking. Once the flow exhausts, prices revert toward where steady-state buyers and
   sellers clear.

2. **Negative dealer gamma.** Options market makers run net-short gamma exposure on indices
   (because retail and institutional buyers prefer to buy calls/puts more than sell them). Sharp
   underlying moves force dealers to hedge in the same direction as the move, amplifying it.
   Once daily/weekly options expire or roll, this amplification reverses — the move then fades.
   Garleanu, Pedersen, Poteshman (2009) — "Demand-Based Option Pricing" — describes this
   inventory-driven price effect. Post-2020, the growth of 0DTE options on US indices has
   intensified this pattern.

3. **Vol-targeting forced rebalancing.** Risk-parity, CTA, and vol-targeting funds collectively
   hold a meaningful slice of index futures exposure. When realized vol spikes, they
   mechanically reduce position size, selling on the way down (or buying back shorts on the way
   up). This sell-pressure overshoots fundamentals; once vol normalises, exposure is rebuilt,
   reverting the price. Bollerslev, Hood, Huss, Pedersen (2018) document the mechanism for
   commodities; equity indices behave similarly.

4. **Liquidity provision premium.** HFT and bank market-makers earn a spread for absorbing
   one-sided flow during extreme moves. The "fade" is the return on that liquidity provision.
   Short-horizon mean-reversion is the empirical signature of this premium, captured by the
   willing-and-able liquidity provider — which our bot can be at the bar-close timescale.

### Why This Edge Is Plausibly Real On Post-2020 Indices

Three regime shifts since 2020 have intensified short-horizon mean-reversion in index prices:

- **0DTE options dominance.** Same-day-expiry options on SPX, QQQ, NDX, IWM now account for 40%+
  of total SPX option volume. Dealer hedging across these contracts is the proximate cause of
  many intraday and overnight reversals on US indices.
- **Faster Fed responsiveness.** Powell-era Fed verbally adjusts policy on shorter timescales
  than prior cycles, producing 1–3 day reversals after macro-driven overshoots.
- **Algorithmic vol-targeting.** Risk-parity and CTA assets-under-management grew through the
  2010s; their mechanical rebalancing flows are a larger fraction of marginal price formation
  than they were in the 1990s–2000s.

The first signal-decay test on this universe found strongly negative formation→forward
correlation in every cell tested — consistent with these mechanisms being active in the current
regime.

### Academic Support

- **Lehmann (1990) — "Fads, Martingales and Market Efficiency" — QJE.** Short-term reversal in
  individual stocks; the original reference for weekly reversal strategies.
- **Jegadeesh (1990) — "Evidence of Predictable Behavior of Security Returns" — JF.** Monthly
  reversal in stocks; complementary horizon to Lehmann.
- **Khandani and Lo (2007) — "What Happened To The Quants In August 2007?"** Demonstrates how
  forced de-leveraging produces predictable reversals after large drawdowns, and how the
  reversal trade is the principal income source for stat-arb funds.
- **Garleanu, Pedersen, Poteshman (2009) — "Demand-Based Option Pricing" — RFS.** Establishes
  the dealer-gamma → underlying-overshoot → reversion mechanism.
- **Nagel (2012) — "Evaporating Liquidity" — RFS.** Argues short-term reversal premium IS the
  liquidity premium; explicitly tradeable.
- **Bollerslev, Hood, Huss, Pedersen (2018) — "Risk Everywhere".** Cross-asset vol-managed
  strategies; documents the vol-targeting feedback loop on macro futures including equity indices.

### Why This Has Better Odds Than The Previous Two Failed Hypotheses

| Concern                       | FX X-sectional Momentum     | Index TSMOM                  | Index Mean-Reversion          |
|-------------------------------|-----------------------------|------------------------------|--------------------------------|
| Universe size needed          | 16+ for reliable rank       | 1+ (each leg independent)    | 1+ (each leg independent)      |
| Universe we have              | 7 (insufficient)            | 4 (sufficient)               | 4 (sufficient)                 |
| Regime fit (2021-2026)        | Hostile -- carry vanished   | Hostile -- mean-reverting    | Favorable -- mean-reverting    |
| Pre-test empirical evidence   | None                        | None                         | All 36/36 signal cells point right way |
| Transaction-cost sensitivity  | High (D1 spreads ~1 bp)     | Low-Medium                   | Medium-High (frequent trades)  |
| FTMO drawdown shape           | Long left tail              | Slow grind                   | Frequent small wins, rare large loss -- **dangerous** without tight stops |

The mean-reversion path has one structural concern not present in the others: **left-tail
risk**. Mean-reversion strategies traditionally exhibit positive skew at the trade level
(many small wins, rare large loss when the "fade" continues into a real trend change). On
FTMO this risk is the strategy's existential threat — tight per-trade stops are non-optional.

---

## Asset Universe

Same 4 indices as the TSMOM test, confirmed available on broker:
- **US500** — S&P 500. Tightest dealer gamma flows, most 0DTE volume.
- **USTEC** — NASDAQ 100. Higher volatility, larger mean-reversion magnitude.
- **US30** — Dow Jones 30. Lower vol, slower reversion.
- **DE40** — DAX 40. European session, partial decorrelation from US three.

**Out:** UK100 and JPN225 (atypical contract specs on this demo broker that need real-FTMO
verification).

---

## Signal Construction

**Primary signal: Short-horizon return z-score**

For each symbol at time T:
- `formation_return(T) = close(T) / close(T - formation_bars) - 1`
- Rolling mean and std of formation_return over a `z_lookback` window (e.g. 252 bars = ~1y).
- `z(T) = (formation_return(T) - rolling_mean(T)) / rolling_std(T)`

Entry conditions:
- **Long-only.** Open long when `z(T) < -entry_threshold` (e.g. z < -1.5 — bottom ~7% of
  historical past-formation z-scores). Price has dropped sharply; bet on bounce.
- **No short entries.** The 2026-05-11 bucket test showed sharp rallies tend to continue
  (positive forward returns in top decile across all 4 indices). The asymmetric flow argument
  in this doc predicts this; the empirical test confirms it.

Exit conditions (ensemble — CLAUDE.md §3 forbids single-signal):
- **Time stop:** close after `max_hold_bars` (e.g. 10 D1 bars) regardless of P&L.
- **Mean-reversion exit:** close when `|z(T)| < exit_threshold` (e.g. |z| < 0.5).
- **Stop-loss:** close at entry +/- `stop_atr × ATR(14)` (e.g. 1.5x ATR — bounds loss
  when mean-reversion fails and a real trend emerges).
- **Take-profit:** close at entry +/- `tp_atr × ATR(14)` (e.g. 2.0x ATR — books partial
  gains before the move fades).

The four exits are evaluated in priority order: stop > take-profit > mean-reversion > time stop.

**Secondary signal: Regime filter**

When realized 20-day vol is in the top 10% of its historical distribution, **pause new entries**.
In high-vol regimes, mean-reversion fails (the move IS the trend). This is the inverse of
TSMOM's risk-off filter.

**Tertiary signal: Trend overlay (kill far-from-trend longs in bear markets)**

When the 200-day EMA is sloping down (close - EMA(200) < some threshold AND
EMA(200) slope is negative), suppress LONG mean-reversion entries on that symbol.
Mirror for SHORT entries in strong uptrends.

This kills trades like "buy the dip in Q1 2022" which would have been catastrophic.

---

## Position Sizing

Same engine as FX momentum, with one modification:
- Per-trade risk: **0.3%** of equity (lower than FX momentum's 0.5% — mean-reversion has higher
  tail risk per trade, so smaller per-trade size is the correct response).
- Kelly fraction: ¼ Kelly, capped at per_trade_risk_pct.
- Stop distance: 1.5× ATR(14).
- Lot size: `(per_trade_risk_pct × equity) / (stop_distance × tick_value / point)`.

---

## Pre-Backtest Empirical Evidence (2026-05-11)

Two tests on the same 4-index universe (US500, USTEC, US30, DE40) over 5y D1:

**Test 1 — Lag correlation.** All 36 formation×holding cells negative across all 4 symbols.
P(all 36 < 0 | iid null) ≈ 1.5e-11. Genuine signal of *something*; couldn't distinguish
long-bias vs short-bias from this statistic alone.

**Test 2 — Decile bucket forward returns (formation=10d, forward=5d).** The asymmetric picture
that justified collapsing to long-only:

| Symbol | D1 forward (deepest dips) | D10 forward (sharpest rallies) |
|--------|---------------------------|---------------------------------|
| US500  | **+0.94% (t=3.18)**       | +0.52% (t=2.35) — rally continued|
| USTEC  | **+1.00% (t=2.31)**       | +1.08% (t=3.92) — rally continued|
| US30   | **+0.64% (t=2.47)**       | +0.39% (t=2.03) — rally continued|
| DE40   | +0.32% (t=0.96)           | +0.88% (t=5.23) — rally continued|

Bottom-decile (deepest 10% of past-10d drawdowns by rolling z-score) shows positive forward 5d
return on **all 4 symbols, statistically significant (t > 2) on 3 of 4.** Top-decile is
positive on all 4 — i.e. selling rallies would have lost money on average. The long-side dip-buy
trade has a clean signal; the short-side rally-fade trade is empirically wrong.

**However:** this is in-sample evidence on the full 5y window. Using it to size the strategy is
fine; using it to *confirm* the strategy works without OOS validation is data-snooping. The
backtest below explicitly walk-forwards (36m IS / 12m OOS) to address this.

---

## Pass/Fail Criteria

Before this strategy can be considered for paper-trading deployment:

1. **Phase 1 bucket signal test (new, not just lag correlation):**
   Bucket past-formation z-score into deciles. Forward 5d return should be monotonically
   positive in low z deciles and negative in high z deciles. If the relationship is non-monotonic
   or the slope is statistically insignificant after Bonferroni correction for 4 symbols, REJECT.

2. **Full-period backtest:**
   - Sharpe ≥ 0.7
   - Max drawdown ≤ 10%
   - Profit factor ≥ 1.2
   - Win rate ≥ 50% (mean-reversion strategies typically have higher hit rate than momentum)
   - FTMO sim PASS on 2-Step Phase 1 spec

3. **Walk-forward (36m IS / 12m OOS):**
   - Mean OOS Sharpe ≥ 0.5
   - IS→OOS degradation ≤ 0.3 (mean-reversion is more regime-dependent than momentum;
     tighter tolerance)
   - Worst OOS window Sharpe ≥ 0.0 (no catastrophic OOS year)

4. **Parameter sensitivity (formation ±20%, entry_z ±20%, exit_z ±20%, max_hold ±20%):**
   - Sharpe std ≤ 0.25 across cells
   - All cells positive Sharpe (mean-reversion has either an edge or doesn't — a fragile
     parameter surface is a serious warning)

5. **Stress tests:**
   - Strategy must not produce any single trade > 2% account loss.
   - Maximum simultaneous-position aggregate risk ≤ 1.5%.

If any of these fail, the strategy is rejected.

---

## Known Weaknesses

1. **Left-tail risk.** Mean-reversion fails violently in regime changes (Aug 2007, March 2020,
   Q1 2022). The vol regime filter and stop-loss must be sized to survive these without account
   failure. This is the principal failure mode.

2. **Frequent trading → cost drag.** Each trade pays spread + slippage + commission. Even at
   index-CFD spreads, ~100 trades per year per symbol × 4 symbols × ~$5/trade = $2,000 in
   annual costs on $100K equity. The backtest must model this honestly.

3. **2020-style correlation breakdown.** When every asset moves the same direction at once
   (March 2020 sell-off), the "fade" trade compounds losses across all 4 indices simultaneously.
   The correlation cap and the regime filter address this but cannot eliminate the risk.

4. **Look-ahead via z-score normalisation.** The z-score uses a rolling lookback of past
   returns. If implemented incorrectly (using future bars in the rolling window), the backtest
   looks far better than reality. Unit tests must verify no-look-ahead.

5. **Regime non-stationarity.** The mean-reversion regime that produced 36/36 negative
   formation-holding correlations in 2021-2026 may not persist. If the underlying flow regime
   shifts (e.g. central banks stop bailing out drawdowns), mean-reversion can collapse to zero
   alpha. The strategy must include a kill switch on rolling 6-month Sharpe.

---

## Regime Conditions Under Which The Strategy Is Active

**Active:**
- Realized 20d vol below 90th-percentile threshold.
- 200-day EMA trend filter not contradicting the entry side.
- No high-impact news in the next 2 minutes (FTMO Funded news gate).
- FTMO headroom ≥ 1% of both daily-line and max-loss line.

**Paused / sized down:**
- Vol regime spike → no new entries.
- 200d EMA strongly opposed to entry direction → skip that side.
- 6-month rolling Sharpe drops below -0.5 → halt new entries until manually reviewed.
- Friday after a defined cut-off (non-Swing accounts) → no overnight holds into weekend.

---

## Risk Controls

In addition to global FTMO gates:

- **Per-trade stop is mandatory** — the failure mode of this strategy IS the unbounded loss
  when reversion doesn't happen.
- **Hold time cap.** `max_hold_bars` enforced even if no other exit triggers.
- **Aggregate position cap.** Sum of open-position risk ≤ 1.5% of equity (mean-reversion
  signals across the 4 indices are positively correlated; treat them as ~2 effective legs).
- **Rolling Sharpe kill.** If 6-month rolling Sharpe falls below -0.5, halt new entries.
- **Daily-loss conservatism.** Set internal daily kill at 2% (tighter than the 3% used for
  FX momentum) to account for the higher per-trade tail risk.
