# Strategy Hypothesis: Regime-Gated JPY-Cross Carry (AUDJPY / NZDJPY)

## One-Line Hypothesis

When the Bank of Japan keeps overnight rates pinned at or near zero while
the Reserve Bank of Australia holds policy rates at 3-5%, the broker
charges *us* a small short-yen funding rate but credits us a large
long-AUD carry yield, producing a +1.5-2.0% annualised carry on AUDJPY
*before* any spot move. Simultaneously, when the Reserve Bank of New
Zealand cuts faster than the BoJ (the canonical 2024-2026 setup), the
carry on NZDJPY compresses to ~0 and the spot trend reverses,
making *short* NZDJPY a positive-expectancy hedge that also earns its
own (smaller) short-side carry. **The combined long-AUDJPY /
short-NZDJPY position earns carry on both legs, has lower vol than
either leg standalone (the AUD and NZD risk-on betas mostly cancel),
and produces a positive expected return as long as the BoJ-vs-RBA rate
gap stays open.**

The position is **regime-gated**: it only fires when the broker swap
itself tells us the rate gap is wide. When swap rates compress toward
zero, the gate closes and the strategy stands down — which is what every
macro fund does on a carry book when rates converge.

This is the third leg of the FTMO portfolio:
- Leg 1: Index Mean-Reversion (D1, US500/USTEC/US30) — slow, fades extremes
- Leg 2: Gold-Silver Pairs (D1, XAUUSD/XAGUSD cointegration) — slow, mean-reverts the spread
- Leg 3: **JPY-Cross Carry (D1, AUDJPY/NZDJPY)** — slow, harvests rate-differential premium

Mechanism-wise all three are different (microstructure mean-reversion,
cointegration mean-reversion, rate-differential risk premium). Per the
hedge-fund deployment principle adopted 2026-05-19: this strategy was
selected after **sweeping the carry mechanism across all available
markets**. Single-pair AUDJPY/NZDJPY beat top-2/bot-2 (Sharpe 0.79 vs
0.57) and top-3/bot-3 (-0.46), confirming the signal is concentrated in
the extreme-carry pairs.

---

## Why This Edge Exists

### Mechanism

1. **The interest-rate parity violation.** Covered Interest Rate Parity
   says the forward exchange rate should fully price the rate
   differential, so carry trades should earn zero in expectation. In
   practice, the *uncovered* parity (the one that matters for spot)
   fails systematically — high-rate currencies earn the carry AND, on
   average, do not depreciate at the rate-differential rate (the "FX
   carry premium" / "forward premium puzzle"). This anomaly is one of
   the most-replicated in academic FX literature (Fama 1984, Lustig &
   Verdelhan 2007, Brunnermeier & Pedersen 2009).

2. **JPY is the world's funding currency.** Japan has held overnight
   rates at or near zero since the 1990s. Every global macro fund and
   institutional carry book sells JPY to fund higher-yielding positions.
   This creates persistent downward pressure on JPY in low-vol regimes,
   which is *exactly* when the carry trade is supposed to work.

3. **Risk-on / risk-off asymmetry.** The strategy works in calm risk-on
   regimes (low VIX, rising equities — when global funds are leveraged
   into carry) and breaks during risk-off shocks (carry unwinds rapidly
   as funds cover JPY shorts). The 2024 Aug 5 BoJ "carry unwind" event
   was the canonical example. **The regime gate (swap-rate-based) is
   our defense against this.**

4. **Microstructure: broker swap > true funding cost.** Retail FX
   brokers calculate swap by referencing the interbank LIBOR-equivalent
   rate differential, plus a margin. For pairs like AUDJPY where the
   AUD interbank curve is well above the JPY curve, the broker passes
   most of the differential through. The carry yield we see in the
   probe (+3.52 $/lot/day on AUDJPY) is real money that lands in the
   account every day at broker rollover.

### Academic / Practitioner Support

- **Lustig, Roussanov, Verdelhan (2011), RFS**, "Common Risk Factors
  in Currency Markets." Documented the HML-FX carry factor: sorting
  currencies by interest rate into 5 portfolios and going long the
  top quintile, short the bottom, earned ~5% annualised excess return
  with Sharpe ~0.7 from 1983-2009.

- **Brunnermeier, Nagel, Pedersen (2008), NBER**, "Carry Trades and
  Currency Crashes." Documented that carry has positive skew during
  calm periods and extreme negative skew during stress, with sharp
  unwinds. Their conclusion: carry pays a risk premium for accepting
  crash risk. The regime gate in our spec is the operational answer.

- **Burnside, Eichenbaum, Rebelo (2011), AER**, "Carry Trade and
  Momentum in Currency Markets." Documented that carry trades have
  been one of the most persistent positive-return strategies in FX,
  surviving even after transaction costs and rare-event corrections.

- **Mancini, Ranaldo, Wrampelmeyer (2013), JFE**, "Liquidity in the
  FX Market." Documented that AUDJPY and NZDJPY are among the most
  liquid carry pairs even during stress, with bid-ask spreads
  comparable to G3 majors.

- **AQR (Asness, Moskowitz, Pedersen 2013, JFin)**, "Value and
  Momentum Everywhere." Replicated the FX carry premium and
  documented its complementary nature to value and momentum factors.

### Why This Should Still Work Post-2014

The robustness sweep (scripts/jpy_carry_universe_sweep.py, 2026-05-19)
shows the L/S top1/bot1 portfolio has been **regime-dependent on this
12y sample**:

- 2014-2018 Sharpe: **-0.70** (Fed-hiking cycle ended too early, BoJ
  expanded QQE — but carry unwinds in 2015-16 China scare hit hard)
- 2019-2022 Sharpe: **-0.22** (COVID + ZIRP convergence)
- **2023-2026 Sharpe: +5.00** (current BoJ-vs-RoW divergence — both
  carry and spot are highly favourable)

The +5.00 Sharpe in the current regime is what we capture. The negative
sub-period Sharpes are what the regime gate *protects against*. The
gate triggers off the broker swap itself: if the AUDJPY swap drops below
+2.00 $/lot/day, the BoJ-vs-RBA gap has compressed and we stand down.

---

## Asset Universe

**Primary:**
- **AUDJPY** (long leg) — broker swap_long currently +3.52 $/lot/day
- **NZDJPY** (short leg) — broker swap_long currently -1.76; short
  earns most of this back via swap_short

**Why not the bot2/bot3 pairs (CADJPY, CHFJPY, EURJPY, GBPJPY)?**
The sweep (jpy_carry_universe_sweep.py) showed that going top-3/bot-3
flipped the Sharpe to -0.46. The marginal pairs (especially EURJPY
which sits in the middle of the carry ranking) add noise without
adding signal. The 6-asset sort collapses to a 2-asset extreme.

**Open question (parallel research):** does the same carry mechanism
deploy better on USD-vs-exotics (USDMXN, USDZAR, USDTRY)? Sweep is
running; if those produce higher Sharpe, may add as a parallel EA.

---

## Signal Construction

### Entry condition (must be ALL true)

1. **No existing position** in either AUDJPY or NZDJPY
2. **Regime gate active**:
   - `SymbolInfoDouble(AUDJPY, SYMBOL_SWAP_LONG) > +2.00` USD/lot/day
   - `SymbolInfoDouble(NZDJPY, SYMBOL_SWAP_SHORT) > +1.00` USD/lot/day
3. **No high-impact CB meeting within ±3 days**: BoJ, RBA, RBNZ
   (loaded from configs/cb_meetings.yaml; for now hardcoded list)
4. **FTMO headroom check passes** for the 1.0% aggregate worst-case

### Exit condition (ANY one fires → flatten both legs)

1. **Take-profit:** total realised P&L (spot + carry) > **+2.0%** of
   entry equity
2. **Stop-loss:** total unrealised P&L < **-1.0%** of entry equity
3. **Time stop:** held >= **60 D1 bars** (~3 months)
4. **Regime halt:** either swap-rate gate condition flips (AUDJPY
   swap_long drops below +1.50 OR NZDJPY swap_short drops below
   +0.50). Note: throttle thresholds are tighter than entry — give the
   position room to breathe before forcing an exit.
5. **News halt:** BoJ/RBA/RBNZ meeting within next 24h → flatten
   pre-emptively (these can flip the carry regime in one announcement)
6. **Rolling Sharpe halt:** 60-bar realised Sharpe of past trades <
   **-0.3** → halt new entries until manual review

### Risk Sizing

- **Per leg:** 0.5% of equity, sized as `lot_size = (equity * 0.005) /
  (1.0 * atr_USDJPY_lot)`. Stop distance for sizing = 1 × ATR(14) of
  the cross.
- **Aggregate:** 2 legs × 0.5% = **1.0%** worst-case (well inside the
  CLAUDE.md 2% cap on aggregate open risk)
- **No leverage stacking:** if either leg fails the headroom check
  individually, neither leg is opened.

---

## Pass / Fail Criteria

Before deploying to MT5:

1. **Bucket test (Phase 3) — DONE:** spot-only L/S top1/bot1 Sharpe
   +0.79, t=+2.74 on 12y D1. Spot+carry Sharpe +1.88 (upper bound;
   assumes today's swap held all 12y).

2. **Full-period backtest (Phase 4) — TODO:**
   - Spot+carry Sharpe ≥ **0.8** annualised
   - Win rate ≥ **45%**
   - Profit factor ≥ **1.4**
   - Max drawdown ≤ **6%** of equity
   - **Regime gate must demonstrably suppress 2014-2018 + 2019-2022
     drawdowns**: with-gate Sharpe must beat without-gate Sharpe by ≥
     +0.5 over those sub-periods
   - FTMO simulator PASS

3. **Walk-forward (Phase 5, 36m IS / 12m OOS) — TODO:**
   - Mean OOS Sharpe ≥ **0.5**
   - All OOS windows FTMO PASS
   - IS→OOS degradation ≤ **0.5**

4. **Correlation with the 2-leg portfolio:**
   - rho < **0.3** with combined Index MR + Pairs equity curve.
   - Different mechanism (rate-diff vs cointegration vs MR) and
     different assets (FX vs metals vs indices) — should be
     mechanically uncorrelated.

---

## Known Weaknesses

1. **The 2024-08-05 carry-unwind risk.** A BoJ surprise hike or a Fed
   surprise cut can cause AUDJPY/NZDJPY to gap 3-5% in a single
   session. Our internal max-loss is 7%, so a single gap can put the
   account near the wall. The news-gate skips ±3 days around scheduled
   CB meetings, but **unscheduled** policy actions (Sep 2022 BoJ FX
   intervention) are unhedgable.

2. **Swap-rate changes are discrete, not continuous.** The broker may
   re-set swap rates intra-week with no warning, especially after CB
   meetings. The regime gate's tightness (throttle at swap_long <
   +1.50) gives some warning but a sudden swap collapse could leave
   us in a position that no longer earns carry while spot still moves
   against us.

3. **Single regime, single sample.** The +5.00 Sharpe in 2023-2026 is
   *one* observation of the favourable regime. The historical record
   contains far more unfavourable regimes. Mean-reverting our prior
   toward the long-term average gives Sharpe in the 0.4-0.8 range,
   not 5+.

4. **Triple-correlation risk with the other two legs.** Although
   nominally uncorrelated by mechanism, in extreme risk-off events
   (2008, 2020-03, 2022-09): gold spikes, indices crash, JPY rallies.
   All three legs of our portfolio could lose simultaneously. The
   per-leg 0.5% risk + portfolio 1.0% aggregate + 5% daily-loss
   internal limit is sized for this.

5. **Static vs dynamic carry ranking.** The strategy uses today's
   swap-rate ranking as if it had been the historical ranking. In a
   true production system, the ranking would re-sort as rate
   differentials evolve, and AUDJPY might cease to be top-1. The
   regime gate partially handles this (if AUDJPY drops out of carry
   favor, the gate closes and we stand down), but a true dynamic-
   ranking version would be more robust.

---

## Regime Conditions

**Active:**
- AUDJPY broker swap_long > +2.00 USD/lot/day
- NZDJPY broker swap_short > +1.00 USD/lot/day
- No scheduled BoJ/RBA/RBNZ meeting in next 3 days or past 3 days
- VIX < 30 (carry breaks during equity panics)
- Rolling 60-day realised Sharpe of strategy > -0.3

**Paused / no-trade:**
- Any regime condition fails
- Within 3 days of a scheduled major central bank meeting
- After a rolling-Sharpe halt (manual restart required)

**Force-flat:**
- FTMO equity-line kill triggers (handled by libftmorisk via the EA)
- BoJ FX intervention announcement (unscheduled, monitored via news
  feed — future enhancement)
- Either swap-rate condition collapses (throttle thresholds)
