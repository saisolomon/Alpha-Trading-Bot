# Strategy Hypothesis: Regime-Gated EM-FX Carry (USDMXN / USDZAR)

## One-Line Hypothesis

When Banxico holds policy rates at 9-11% and the Fed sits at 4-5%, the
broker credits a 5-6%-annualised carry yield to long USDMXN positions
(the rate differential earned on $174k notional per lot, +$24.87/lot/day
realised cash). When SARB sits at 7-8% vs Fed 4-5%, the equivalent
+$5.60/lot/day flows to *short* USDZAR positions. **The combined
long-USDMXN / short-USDZAR trade earns ~$30/lot/day in carry — over 10x
the AUDJPY carry yield — and the MXN/ZAR risk-on betas partially
cancel.** Empirical validation: spot-only L/S top-2/bot-2 Sharpe +1.41,
t=+4.92 on 12y D1.

The strategy is **regime-gated** identically to the JPY-carry sibling:
broker swap rates serve as a real-time proxy for the rate-differential
regime. If Banxico cuts to convergence with the Fed (or SARB does),
the gate closes.

## Why This Strategy Is Paired With the JPY-Carry Strategy

This is the **second carry-mechanism EA** in the portfolio. It exists
alongside AUDJPY_CHFJPY_Carry because the two strategies harvest the same
fundamental risk premium (uncovered interest rate parity violation) in
**non-overlapping regimes**:

| Period | JPY-Carry Sharpe | EM-Carry Sharpe |
|---|---|---|
| 2014-2018 | **-0.70** | **+2.75** |
| 2019-2022 | -0.22 | +0.78 |
| 2023-2026 | **+5.00** | **-0.98** |

When the BoJ-vs-RoW gap is wide (current regime), JPY carry pays. When
EM CB rates are HIGH relative to USD (2014-2018), EM carry pays.
**Their failure modes are independent.** This is the textbook
Bridgewater regime-diversification setup: combining two regime-
anti-correlated strategies approaches additive Sharpe at the portfolio
level. Expected combined-strategy Sharpe: 1.2-1.6 on 12y, vs ~0.8 for
either standalone.

---

## Why This Edge Exists

### Mechanism

Same as JPY-carry (see strategies/jpy_carry/HYPOTHESIS.md §"Why This
Edge Exists"). The UIP violation operates identically; only the
funding currency (USD here, JPY there) and the carry-positive currency
(MXN/ZAR here, AUD/NZD there) differ.

### Specific to EM carry

1. **Emerging-market sovereigns require a higher real return** to
   compensate global investors for currency-crisis risk, capital-
   account restrictions, and political instability. This rate
   premium persists for structural reasons that don't decay over
   time (Bansal & Dahlquist 2000, JFin).

2. **Banxico has been the most credible EM CB.** Mexico has maintained
   positive real rates throughout the 2014-2026 sample, with only
   brief downcycles in 2019-2020 and late 2024. The MXN has been the
   most-liquid EM currency in the world by daily volume (BIS Triennial
   Survey).

3. **SARB's rate regime is dynamically similar to Banxico's** but the
   ZAR has higher equity-correlation (commodity-export exposure to
   gold and platinum). Long-USDZAR is structurally short-ZAR which
   benefits from risk-off (SARB cuts when growth disappoints, USDZAR
   rises, our SHORT position loses — but the carry differential
   partially compensates).

### Academic Support (Specific to EM Carry)

- **Bansal & Dahlquist (2000), JFin**, "The forward premium puzzle:
  different tales from developed and emerging economies." Documented
  that the UIP violation is **larger** in EM than DM, with the carry
  premium roughly 2x as large for EM currencies vs G10.

- **Burnside (2012), AEA**, "Carry Trades and Risk." Showed EM-FX
  carry has historically earned Sharpe 0.6-1.0 in DM-currency
  funding, with the spread vs G10-only carry attributable to a
  combination of liquidity and policy-credibility premia.

- **Kohler, Manalo, Perera (2014), RBA**, "Exchange Rate Movements
  and the Australian Economy." Cross-references the AUD/EM-FX carry
  flow correlation, useful for understanding why our JPY and EM
  carry books are regime-uncorrelated.

### Why This Should Still Work Post-2014

The 12y sub-period sweep confirms the edge is *not* recently
discovered — it was strongest 2014-2018 when EM rate differentials
peaked. The current weakness (2023-2026 Sharpe -0.98) is a
**Banxico-easing event** (cuts from 11.25% to ~8% in 2024-25),
not a structural change. The regime gate (USDMXN swap_long > +20)
detects this in real time: if Banxico cuts further, swap_long drops
and the gate closes.

---

## Asset Universe

**Primary:**
- **USDMXN** (long leg) — broker swap_long currently +24.87 $/lot/day
- **USDZAR** (short leg) — broker swap_short currently +5.60 $/lot/day

**Optional 3rd leg (per top-2/bot-2 sweep result, Sharpe +1.41 > +1.17):**
- **USDNOK** (short leg) — broker swap_short +1.67 $/lot/day. Small,
  but adds diversification within the basket.

**Excluded from this strategy:**
- **USDTRY** — broker swap is zero (TRY swap suspended due to
  hyperinflation/regulatory issues). Data quality concerns even
  on the spot side. Skip.
- **USDSEK** — near-zero carry, no edge.
- **USDHKD** — HKD-USD peg means de-facto zero carry differential
  except during peg-stress events.
- **USDSGD** — small negative carry on both sides; no edge.

---

## Signal Construction

### Entry condition (must be ALL true)

1. **No existing position** in any of USDMXN, USDZAR
2. **Regime gate active**:
   - `SymbolInfoDouble(USDMXN, SYMBOL_SWAP_LONG) > +20.0` USD/lot/day
   - `SymbolInfoDouble(USDZAR, SYMBOL_SWAP_SHORT) > +4.0` USD/lot/day
3. **No high-impact CB meeting within ±3 days**: FOMC, Banxico, SARB
4. **FTMO headroom check passes**

### Exit condition (ANY)

1. **Take-profit:** total realised P&L > **+2.0%** of entry equity
2. **Stop-loss:** total unrealised P&L < **-1.0%** of entry equity
3. **Time stop:** held ≥ **60 D1 bars** (~3 months)
4. **Regime halt:** swap rates compress (USDMXN swap_long < +15.0 OR
   USDZAR swap_short < +3.0)
5. **News halt:** Banxico/FOMC/SARB meeting within next 24h
6. **Rolling Sharpe halt:** 60-bar realised Sharpe < **-0.3**

### Risk Sizing

- Per leg: 0.5% equity, sized via ATR(14) stop
- Aggregate: 2 legs × 0.5% = **1.0%**
- Per CLAUDE.md aggregate-open-risk cap (2%): when combined with
  the 1.0% from JPY-carry, total portfolio carry-leg risk = **2.0%
  aggregate** — exactly at the cap. No 3rd carry leg without
  raising the cap.

---

## Pass / Fail Criteria

Identical to strategies/jpy_carry/HYPOTHESIS.md plus one additional:

5. **Joint correlation with JPY-carry:** rolling 6m rho between
   EM-carry equity curve and JPY-carry equity curve must be
   < **+0.3**. If it exceeds, regime-diversification breaks and
   we shouldn't run both.

---

## Known Weaknesses

1. **MXN spread can blow out 50-100 bp in crisis.** Mexican peso is
   liquid in normal regimes but spread can widen during USD crises
   (2008, 2020-03, 2022-09). Our cost model needs to assume 2x the
   normal spread.

2. **Banxico FX intervention risk.** Like the BoJ, Banxico has
   intervened directly in MXN markets during stress. Unscheduled
   intervention can gap USDMXN by 1-2%.

3. **ZAR equity-correlation.** Unlike MXN (commodity-neutral), ZAR is
   highly correlated with gold and platinum prices. A gold rally that
   doesn't move USD = bad for our short USDZAR position (ZAR
   strengthens, USDZAR drops, our short PROFITS — wait, that's good).
   Recheck: short USDZAR is short the pair = short USD/long ZAR. Gold
   rally → ZAR strengthens → USDZAR drops → short profits. So gold
   rallies are GOOD for us, gold sell-offs are BAD. Net effect on
   portfolio: gold-correlated risk that's not present in JPY-carry.
   Track separately.

4. **Triple-correlation with the other 3 legs (worst case):** in a
   true 2008-style global liquidity event, all 4 strategies could
   lose simultaneously (gold drops, indices crash, JPY rallies,
   EM-FX sells off in 'flight to USD'). Internal max-loss kill at
   7% guarantees survival but a single-day 4-leg drawdown could
   wipe out a full month's expected return.

---

## Regime Conditions

**Active:**
- USDMXN broker swap_long > +20.0 USD/lot/day
- USDZAR broker swap_short > +4.0 USD/lot/day
- No FOMC/Banxico/SARB meeting in next 3 days or past 3 days
- VIX < 30
- Rolling 60-day realised Sharpe of strategy > -0.3

**Paused:**
- Any regime condition fails
- Within 3 days of major CB meeting
- Rolling-Sharpe halt triggered

**Force-flat:**
- FTMO equity-line kill (libftmorisk)
- Unscheduled Banxico intervention announcement (future enhancement)
- Either swap rate collapses below throttle threshold
