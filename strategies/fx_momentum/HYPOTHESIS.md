# Strategy Hypothesis: FX Cross-Sectional Momentum

## One-Line Hypothesis

Currency pairs exhibit persistent cross-sectional return dispersion over 1–3 month horizons because
institutional capital rebalancing is gradual — slow-moving flows create trends that are detectable
and exploitable before they fully mean-revert.

---

## Why This Edge Exists

### The Economic Mechanism

1. **Slow capital rebalancing.** Pension funds, sovereign wealth funds, and asset managers
   rebalance FX exposure quarterly or annually. A fund rotating from EUR to USD doesn't do it in
   one trade — it leaks into the market over weeks, creating persistent directional pressure.

2. **Carry and momentum interact.** High-yield currencies attract carry flows, which self-reinforce:
   inflows push the currency higher, attracting momentum followers, which pushes it higher still.
   The trend continues until the carry unwinds (volatility spike, risk-off) or the yield differential
   closes.

3. **Information diffusion is heterogeneous.** Macro data (PMIs, rate expectations, trade balances)
   is not instantly priced by all participants. Informed actors (CB-connected banks, large hedge
   funds) accumulate positions before the information becomes consensus — creating the "trend"
   that less-informed actors later chase.

4. **Under-reaction, not over-reaction.** Unlike equities where momentum is partly explained by
   over-reaction, FX momentum appears to be under-reaction: currencies keep drifting toward
   their fair value (e.g., the interest-rate differential implied by PPP or UIP) long after the
   signal that should have driven the move appeared.

### Academic Support

- Menkhoff et al. (2012) "Currency Momentum Strategies" — JFE. Sharpe ratios of 0.5–1.0 on a
  diversified cross-sectional momentum portfolio of 48 currencies, 1976–2010.
- Asness, Moskowitz, Pedersen (2013) "Value and Momentum Everywhere" — JF. Momentum is
  pervasive across asset classes; FX is one of the most reliable.
- Barroso and Santa-Clara (2015) "Momentum Has Its Moments" — JFE. Momentum is dangerous
  in high-volatility regimes; a vol-targeting overlay significantly improves Sharpe.

---

## Signal Construction

**Primary signal: Cross-sectional return rank (momentum)**
- Formation period: 20 D1 bars (≈ 1 month), skipping the most recent 1 bar (avoids short-term reversal).
- For each symbol at time T: `return(T) = close(T-1) / close(T-21) - 1`
- Z-score across the universe to normalize: `z = (return - mean) / std`
- Long symbols with z-score > +0.5, Short symbols with z-score < -0.5, Flat otherwise.

**Secondary signal: Trend confirmation (EMA cross)**
- A long signal requires price > 50-bar EMA (trend is up at the current timeframe).
- A short signal requires price < 50-bar EMA (trend is down).
- This kills signals that are fighting the prevailing trend — momentum confirmation.

**Regime filter: Cross-sectional volatility**
- Compute rolling 5-day standard deviation of the cross-sectional z-scores.
- If cross-sectional vol > threshold (2.0 sigma), all signals go flat (crisis / deleveraging mode).
- Rationale: Menkhoff et al. (2012) show momentum crashes during high-volatility episodes; the
  vol filter switches off the strategy during these drawdown-prone periods.

---

## What We're Long / Short

- Universe: 7 FX majors vs. USD — EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCAD, USDCHF.
- Note: USDJPY, USDCAD, USDCHF are quoted inverted (USD is base). The signal normalizes this
  by computing all returns from the perspective of the foreign currency vs. USD — for these pairs,
  the return is inverted before ranking.
- Long top-ranked currency vs. USD, Short bottom-ranked currency vs. USD.
- Maximum 2 longs + 2 shorts at any time (concentration cap for FTMO aggregate-risk limit).

---

## Expected Characteristics

| Metric               | Target       | Rationale                                |
| -------------------- | ------------ | ---------------------------------------- |
| Sharpe (backtest)    | 0.6 – 1.2    | Menkhoff et al. baseline ≈ 0.9 with costs |
| Win rate             | 45 – 55%     | Momentum: fat tails, not high win rate    |
| Avg holding time     | 5 – 15 days  | Rebalancing weekly on D1 signal           |
| Max drawdown         | < 15%        | Vol-scaling should bound this             |
| FTMO compatibility   | Yes          | Holding time >> news window; per-trade risk capped at 0.5% |

---

## FTMO Compatibility Analysis

| FTMO Rule                | Risk Level | Mitigation                                   |
| ------------------------ | ---------- | -------------------------------------------- |
| 5% daily loss (2-Step)   | LOW        | Per-trade risk 0.5%; max 4 positions = 2% aggregate |
| 10% max loss (2-Step)    | LOW        | Internal kill at 7%; vol filter reduces crisis exposure |
| News restriction (funded)| MEDIUM     | D1 rebalancing means entries rare near news; gate enforced |
| Weekend gap              | MEDIUM     | Flatten Friday 21:00 Prague; re-enter Monday open |
| Best Day rule (1-Step)   | LOW        | Momentum is gradual; single-day outliers uncommon |
| Copy trading             | NONE       | Single bot, single account; this strategy has no mirror |

---

## Known Weaknesses and Edge Erosion Scenarios

1. **Momentum crashes.** The worst drawdowns in momentum strategies happen fast — volatility spikes
   compress the spread between winners and losers in hours. The regime filter helps but doesn't
   eliminate this risk. Position sizing must be conservative.

2. **Transaction cost sensitivity.** Cross-sectional momentum on FX is modestly profitable after
   costs; wide spreads or excessive rebalancing kill the edge. We use D1 rebalancing (low turnover)
   and trade only liquid majors (tight spreads). Cost model must be realistic.

3. **Crowding.** If momentum is well-known (it is), crowded trades amplify drawdowns when the
   crowd exits. We can't directly measure crowding; diversification and vol-scaling are the hedges.

4. **Regime change.** If central banks globally suppress trend-following (e.g., coordinated
   intervention), or if HFTs fully absorb the slow-rebalancing alpha, the edge erodes. Monitor
   rolling 12-month Sharpe; if it drops below 0.3, reassess.

5. **Small universe.** 7 symbols is a thin cross-section. More symbols would improve robustness
   but FTMO restricts to MT5-available instruments with tight spreads. This is an accepted constraint.
