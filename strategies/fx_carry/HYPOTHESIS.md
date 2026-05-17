# Strategy Hypothesis: FX Carry (with Vol-Regime Filter)

## One-Line Hypothesis

Currencies with high short-term interest rates (carry-yielders like AUD, NZD)
**earn a positive risk premium** over low-yielders (JPY, CHF, EUR) on average,
because uncovered interest parity (UIP) systematically fails in the short-term:
the high-yielder does NOT depreciate by enough to offset its rate advantage.
We harvest this premium by going long high-carry pairs and short low-carry
pairs, **but pause the strategy when realised cross-asset vol is in the top
20% of its distribution** — that's when carry crashes happen.

## Why This Edge Exists

### The Economic Mechanism

1. **Uncovered Interest Parity (UIP) fails empirically.** UIP says
   `E[FX change] = interest_rate_differential` (the high-yield currency
   should depreciate by exactly its rate advantage). In real data, the
   slope coefficient is typically NEGATIVE or near zero — high-yielders
   appreciate slightly OR don't depreciate at all over 1-12 month horizons.
   This is the "forward premium puzzle" (Fama 1984), one of the most
   robust anomalies in international finance.

2. **Risk premium for crash exposure.** The carry trade has a fat-tailed
   left skew: occasional violent unwinds (Aug 2007, Sep 2008, March 2020)
   wipe out years of accumulated carry. The premium is COMPENSATION for
   bearing this crash risk — like selling out-of-the-money put options.
   Brunnermeier-Nagel-Pedersen (2009) "Carry Trades and Currency Crashes"
   documents the skew and the crash mechanism (funding-liquidity spiral).

3. **Capital flow inertia.** Yield-seeking pension / insurance / sovereign
   wealth flows are slow-moving; they continue to allocate to higher-yielders
   even when the spot moves modestly against them, providing persistent
   demand that supports the carry currencies in normal times.

4. **Hedging cost asymmetry.** Funding-currency holders (Japanese savers
   holding JPY) hedge selectively when vol spikes, creating quasi-stable
   demand for yen at calm times and sudden flight-to-yen during stress.

### Academic Support

- **Fama (1984), JME** — original documentation of UIP failure.
- **Lustig & Verdelhan (2007), AER** — "The Cross Section of Foreign
  Currency Risk Premia and Consumption Growth Risk." Carry sorted-portfolio
  approach; positive Sharpe across 30+ years pre-2007.
- **Brunnermeier, Nagel, Pedersen (2009), NBER** — "Carry Trades and
  Currency Crashes." The crash-risk framework. Critical reading.
- **Menkhoff, Sarno, Schmeling, Schrimpf (2012), JF** — "Carry Trades
  and Global Foreign Exchange Volatility." Establishes the vol-state
  dependence we exploit: carry returns are negative when VIX is high.
- **Burnside et al. (2011), AER** — risk-neutral pricing of the carry
  premium. Confirms the premium is compensated risk, not free money.

### Why The Vol-Regime Filter Matters

Per Menkhoff et al. (2012):
- Carry returns are STRONGLY negative when global FX vol (a basket of
  realised vols across G10) is in its top quintile.
- Carry returns are MOSTLY positive in the bottom 80% of vol regimes.
- A simple vol-regime filter (skip the top 20%) historically lifted
  carry Sharpe from ~0.5 to ~0.9 by sidestepping the crashes.

This filter is what makes carry deployable on a FTMO-style equity-line-
sensitive account. Without it, a single carry-crash month (-15% typical)
blows the 10% FTMO line.

## Asset Universe

The same 7 USD-quoted G10 pairs we already have cached (12y D1):

```
EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCAD, USDCHF
```

Per the 2026-05-17 broker probe (see scripts/probe_fx_swap_rates.py output):

| Pair | Long-side daily swap ($/lot) | Annualised long carry on ~$70k notional |
|---|---|---|
| **AUDUSD** | **+6.30** | **+3.2%/yr** |
| **NZDUSD** | **+2.80** | **+1.4%** |
| USDCHF | +0.13 | +0.06% |
| USDJPY | −0.06 | −0.03% |
| GBPUSD | −0.20 | −0.05% |
| USDCAD | −0.58 | −0.15% |
| **EURUSD** | **−0.70** | **−0.22%** (short side preferred) |

The classic carry portfolio:
- **Long top-2 high-carry**: AUDUSD, NZDUSD
- **Short bottom-2 low-carry**: EURUSD, USDCAD (or alternatively short
  EURUSD-equivalent via long EURJPY etc., but we stick to direct USD pairs)
- Equal dollar-notional on each leg for market-neutrality vs USD

## Signal Construction

**Primary signal — relative carry rank.**

At each Prague-midnight boundary, rank the 7 pairs by their long-carry
yield (broker swap_long converted to $/lot/day). Build the portfolio:

  long  the top-N pairs by carry (currently N=2: AUD, NZD)
  short the bottom-N pairs by carry (currently N=2: EUR, CAD)
  equal dollar-notional per leg

**Secondary signal — vol-regime filter.**

Compute a "global FX vol" index daily:

  vol_index_t = mean over the 7 pairs of: rolling(20-bar) std of log returns

If `vol_index_t > quantile(vol_index, 0.80, lookback=504bars)`:
  -> PAUSE all carry positions (close existing, no new entries)

Else: hold the carry portfolio.

**Rebalancing:** Monthly (every 20 D1 bars). Carry rankings change slowly;
monthly rebalance balances signal freshness against transaction costs.

## Position Sizing

Carry has a different sizing profile than mean-reversion -- the "stop"
isn't ATR-based per trade, it's the vol-regime filter at the portfolio
level. Sizing rules:

- **Per-pair notional**: equal across legs (true carry-rank weighting,
  not vol-weighting -- the carry premium is per-currency, not per-unit-vol).
- **Total portfolio gross exposure**: capped at 50% of equity ($50k on
  $100k account). At 2 long + 2 short, that's ~$12.5k notional per leg,
  i.e. ~0.18 lots of AUDUSD ($71k * 0.18 = ~$12.8k).
- **Maximum portfolio loss budget per rebalance**: 1.5% of equity
  ($1500 on $100k). The vol filter is what enforces this; if a carry
  crash bypasses the filter (large gap intraday), the FTMO state machine's
  internal kill at 3% catches the second-line defense.

## Pass / Fail Criteria

Before this strategy can be deployed:

1. **Bucket test:** the high-carry quintile should have positive forward
   1-month return on a static-signal backtest (rank carriers by current
   broker swap, hold the top-quintile for 1 month, repeat). t-stat > 1.5.
2. **Full-period backtest with vol filter:** Sharpe >= 0.4, max DD <= 8%,
   12y FTMO PASS.
3. **Vol-filter validity test:** the strategy without the vol filter should
   have a larger max DD than with the filter -- confirming the filter
   actually fires during crashes.
4. **Correlation with existing 2-strategy portfolio:** rho < 0.3 with
   the Index MR + Gold-Silver Pairs combination. THE key diversification
   gate.
5. **Standalone walk-forward (36m IS / 12m OOS):** mean OOS Sharpe > 0.3.

## Known Weaknesses

1. **Carry-crash skew is the entire reason the premium exists.** The
   vol filter mitigates but does not eliminate the left tail. In the
   one carry-crash month per 1-3 years that slips through the filter,
   expect a 5-15% drawdown.

2. **Static vs dynamic rate signal.** This implementation uses the
   broker's CURRENT swap_long as a static signal -- carry rankings
   actually change as central banks move. For a 2-year deployment
   window the ranking shifts are tiny (AUD has been the high-yielder
   for 20+ years), but in a regime change (e.g. BoJ tightening sharply
   while RBA cuts) the strategy's ranking would lag. Future work: pull
   live rates and refresh signal monthly.

3. **EUR carry is currently slightly negative, not dramatically so.**
   The short EUR leg's carry contribution is modest. The strategy's
   edge mostly comes from the long AUD/NZD side. If AUD's yield advantage
   compresses (RBA cuts to match Fed), the strategy's expected return
   collapses.

4. **Position is overnight ALL THE TIME.** Carry requires holding through
   triple-swap nights (Wednesday rollover at most brokers includes Sat+Sun).
   Weekend gap risk is the principal short-horizon failure mode -- the
   vol filter should catch it but Sunday-open gaps fire before any
   monitor can react.

5. **News-blackout (Funded Standard accounts).** Carry positions held
   over high-impact news (NFP, FOMC, RBA meetings, ECB meetings) are
   exposed to 2-min news-window violation risk. On Funded Standard
   we'd need to flatten before each major event. On Challenge / Swing
   we're fine.

## Regime Conditions

**Active:**
- vol_index <= 80th percentile of trailing 2-year window
- No major scheduled central-bank event in the next 2 days
  (Funded Standard only; ignore on Challenge / Swing)
- Friday close: flatten if account is Funded Standard (weekend hold disallowed)

**Paused / sized down:**
- vol_index > 80th percentile -> CLOSE ALL legs, halt new entries until
  vol normalises.
- Rolling 6-month Sharpe < -0.3 -> halt for manual review.
- Friday after defined cut-off (non-Swing) -> flat into weekend.
