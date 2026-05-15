# Memory.md — FTMO MT5 Quant Trading System

> The persistent memory of this project. Every non-obvious decision, every painful bug, every learning that future-you (or future Claude) will need. Append-only, newest at the top of each section. **If you fix something tricky, log it here — or you will fix it again in three months.**

---

## How to Use This File

- **Decisions** — choices made that someone could plausibly second-guess later. Always note the date, the context, and the *why*.
- **Learnings** — empirical findings (signal didn't work, parameter sensitivity, regime behavior).
- **Gotchas** — non-obvious bugs, MT5 quirks, library traps. Future-you will hit them again without this.
- **Open Questions** — things you don't know yet but have started thinking about.

Format every entry with a date stamp `YYYY-MM-DD`. Append at the top of each subsection (newest first).

---

## Decisions Log

### Architecture & Tooling

### 2026-05-03 — Engine choice: hand-rolled Python on MT5 (locked while on FTMO)
**Context:** Evaluated NautilusTrader (Rust-native, research-to-live parity, vastly better engine), QuantConnect/LEAN (cloud-first, subscription), and a hand-rolled Python engine on MT5.
**Options considered:**
- A) Hand-rolled Python on MT5
- B) NautilusTrader + Interactive Brokers
- C) QuantConnect / LEAN
**Decision:** A (hand-rolled Python on MT5).
**Rationale:** The deployment target is FTMO. FTMO supports MT4, MT5, and cTrader only. NautilusTrader has no MT5 adapter and would require leaving FTMO to use Interactive Brokers — defeating the purpose. QuantConnect is a fine product but is broker-bound to its own integrations and pulls the project into a cloud subscription model. The hand-rolled engine is more work but is the only path that lets the bot run on FTMO capital.
**Reversibility:** The migration to NautilusTrader is planned for post-FTMO (Milestone 9, Path B). Code that touches MT5 (data layer, execution layer) must be considered MT5-coupled and will be replaced. Code that is engine-agnostic (signal logic, risk math, FTMO-rule machine adapted to internal-only limits, backtest metrics) should be portable.

### 2026-05-03 — Data vendor: broker data for now, Databento at Milestone 9 / Path B
**Context:** Evaluated Databento (direct-from-exchange, nanosecond timestamps, $125 free credit, pay-per-GB).
**Decision:** Use FTMO broker data through MT5 for Phase 1 strategies (FX majors, index CFDs). Add Databento only if the migration to Nautilus + IBKR happens AND scope expands to CME futures or full order book.
**Rationale:** Databento adds no value while on FTMO — FTMO's MT5 broker provides the data feed and Databento has no path into MT5. It becomes valuable only in the post-FTMO Nautilus stack, and only for asset classes (futures, full L3 order book) that aren't in current scope.
**Reversibility:** Easy. Add as a data adapter in the post-FTMO repo if needed.

**Template for new entries:**
```
### YYYY-MM-DD — <short title>
**Context:** What were we deciding?
**Options considered:** A vs. B vs. C, with trade-offs.
**Decision:** Picked X.
**Rationale:** Why X over the others.
**Reversibility:** Easy / medium / hard to change later.
```

---

### Strategy Decisions

*No entries yet.*

---

### Risk & Execution Decisions

*No entries yet.*

---

## Learnings Log

### Signal & Alpha Research

### 2026-05-15 -- Search for second uncorrelated strategy -- four failed candidates
**Goal:** Find a second strategy uncorrelated with Index MR to enable a portfolio book worthy of FTMO deployment (Index MR alone is too slow at 1.2% CAGR to pass Phase 1).

**Candidates tested, in order:**

1. **Index TSMOM (4 indices, 5y)** -- already rejected 2026-05-11 at signal-decay stage. All 36 cells negative correlation; TSMOM does not exist on this universe in this regime.

2. **Metals TSMOM (XAUUSD/XAGUSD/XPTUSD, 12y)** -- failed signal-decay test. Cross-universe lag-20-120 average autocorrelation = -0.014 / -0.019 / -0.020 (negative when TSMOM expects positive). 26 of 27 formation->holding cells negative. Same anti-momentum signature as indices.

3. **Metals long-only MR (bucket test, 12y)** -- failed. Inconsistent across the three: gold has bullish drift across all deciles (no clean dip-bounce), silver no signal, platinum has rally-fade (opposite asymmetry from indices). Building from this would be curve-fitting to fragmented results.

4. **FX MR (EURUSD/GBPUSD/AUDUSD, 12y)** -- viable but too weak to deploy. Bucket test on 7 majors found only EURUSD statistically significant (t=-3.07); 12y backtest on the 3 long-side-positive pairs gave full IS Sharpe 0.06, 9 OOS windows mean Sharpe 0.27 / median 0.45, 67% positive. Worst window -1.07 Sharpe. Max DD -9.02% (close to FTMO -10% line).

**The 50/50 portfolio test was the decisive measurement:**
  - Correlation between Index MR and FX MR daily returns: **+0.136** (EXCELLENT diversification, n=3116 aligned days)
  - 50/50 portfolio: Sharpe 0.31 (vs Index MR alone 0.38), CAGR 0.69% (vs 1.20%), Vol 2.25% (vs 3.20%), MaxDD -5.36% (vs -6.68%)
  - **Sharpe DROPPED** despite excellent correlation. Why: adding a near-zero-Sharpe uncorrelated strategy doesn't lift portfolio Sharpe -- it just shrinks the contribution from the strategy that actually works. The math: sqrt(1+rho) vol reduction is dominated by mu reduction when mu2 << mu1.
  - Calmar ratio: 2.31 alone -> 1.59 portfolio. Net worse.

**Pattern across all four candidates:** post-2014 macro regime on FTMO-accessible D1 markets is dominated by mean-reversion on equities, weak/noisy everywhere else. Time-series momentum failed on every asset class tried (indices and metals). Mean-reversion outside equities is either too weak (FX) or inconsistent across the universe (metals).

**Implications for next direction:**
  - The "easy" diversifier searches are exhausted on D1. The honest options are:
    a) **Different timeframe** -- test the same MR signal on H4 indices. Higher trading frequency may compound to higher Sharpe; gamma-flow mean-reversion is academically stronger at intraday horizons. Risk: transaction costs scale unfavorably.
    b) **Different universe** -- try crypto (BTCUSD/ETHUSD if broker offers; check). Crypto has different macro drivers and has been mean-reverting at extreme moves (Khandani-Lo type pattern). Different regime sensitivity.
    c) **Different signal mechanism on same universe** -- volatility-regime strategies (sell vol in calm, buy vol in stress), or breakout strategies (buy on confirmed range break). Distinct from MR mechanism.
    d) **Accept the single-leg classification** -- run Index MR alone, paper-trade for 4 weeks, decide deployment based on live tracking error vs backtest. Don't chase a second leg that doesn't exist in this regime.
  - Memory.md preserves the negative results so future sessions don't waste cycles re-testing the same ideas.

**Files added (kept as research artifacts even though strategy not deployed):**
  - scripts/probe_commodities.py
  - scripts/run_fx_meanrev_backtest.py
  - scripts/portfolio_correlation.py

### 2026-05-11 -- Index Mean-Reversion -- spread stress + 12y walk-forward findings
**What changed:** Re-ran the validated mean-reversion strategy with two methodological upgrades and an extended dataset.
1. **Gap-fill model added** to backtest/meanrev_engine.py. Previously ATR-stop / ATR-TP exits always filled at stop_price / tp_price exactly; now if bar opens past the level (gap-through), fills at bar_open (worse for stops, better for TPs). Realistic behaviour.
2. **Exit slippage cost added** to CostModel.slippage_cost() and applied to ATR stop / ATR TP fills. The previous engine charged slippage only on market entries/exits, not on triggered exits; in reality the bid-ask spread costs you on EVERY round-trip. Net effect on 5y baseline result: Sharpe 0.48 -> 0.47 (small).
3. **Extended dataset** to 12y D1 (2014-05 to 2026-05) for US500 / US30 / DE40 (USTEC capped at 3.8y by broker history).

**Spread stress test (0.5x to 5x baseline spreads):**
  - IS Sharpe: 0.47 -> 0.46 (5x baseline)
  - OOS avg Sharpe: 0.99 -> 0.98
  - Total return: +8.1% -> +7.8%
  - FTMO PASS at every multiplier.
  - Conclusion: strategy edge does NOT depend on tight spreads. Break-even is well above 5x baseline (~250 pts on US500). Strategy is robust to live broker conditions.

**12-year backtest (vs the previous 5y "candidate" claim):**
  - Full IS: Sharpe **0.38**, total return +15.45% over 12 years (~1.2% CAGR), max DD -6.68%, 194 trades, win 55.2%, PF 1.34. FTMO PASS.
  - 9 walk-forward OOS windows (2017-2026): mean OOS Sharpe **0.49**, median **0.27**, 78% positive. IS->OOS degradation -0.11.
  - Worst OOS year (2019-2020): Sharpe **-0.52**, return -1.9%, win 35.7%, PF 0.61. Strategy gave whipsaw entries in the pre-COVID + crash-onset period. FTMO still PASS (max DD never breached).
  - 2022-2023 bear: strategy correctly hibernated (vol filter paused entries) -- only 6 trades, near-zero return.
  - Best OOS year (2020-2021): Sharpe 1.81 but only 3 trades -- statistical noise from a single great signal during V-shaped post-COVID rally.

**Honest reassessment of the 5y "candidate" classification:**
  - The original 2-window walk-forward on 5y data was LUCKY -- it spanned the strategy's two best post-COVID years and missed the 2019-2020 negative year and the 2022 hibernation.
  - Median OOS Sharpe across 9 years is 0.27, not the 1.01 reported on the 2-window test. The 0.27 number is the more honest single-year expectation.
  - The signal is REAL (78% positive years, IS->OOS degr negative, parameter surface flat) but it is a **modest satellite alpha**, not a primary FTMO Challenge candidate by itself.

**Implications for deployment plan:**
  - At 0.5% per-trade risk, 12y total return = 15% -> CAGR 1.2%. Passing FTMO Phase 1 (10% target, no time limit) would take ~7-8 years on average -- impractical alone.
  - Scaling to 1% per-trade risk would double return AND double max DD to ~13% -- breaches FTMO -10% line. Cannot simply size up.
  - **Path to deployment:** combine with 2+ uncorrelated strategies as portfolio legs. The mean-reversion leg contributes ~0.5 Sharpe consistent low-vol grind; needs complementary strategies that fire in DIFFERENT regimes (trending, range-bound, vol-spike) to lift portfolio Sharpe to deployment level.
  - **Worth keeping a kill-switch:** if rolling 6-month Sharpe drops below -0.5, halt. The 2019-2020 OOS window is exactly this scenario -- the strategy was wrong for ~12 months. Real-money should not ride a -0.5 Sharpe for a full year.

### 2026-05-11 -- Index Mean-Reversion Long-Only (US500, USTEC, US30, DE40) -- candidate
**Hypothesis tested:** After a 5-20 day drawdown deep enough that the rolling z-score of past-formation return is < -1.0 (~bottom 15% of historical drawdowns), equity index CFD prices bounce over the next 1-10 days. Long-only entry; symmetric short side rejected by 2026-05-11 bucket test (top decile forward returns positive on all 4 indices -- big rallies kept rallying). Mechanism: asymmetric institutional flow (most equity capital long-only -- dips attract reversion flow, rallies have no equivalent fade pressure), dealer-gamma overshoots, vol-target rebalancing. References: Lehmann 1990, Jegadeesh 1990, Khandani-Lo 2007, Garleanu-Pedersen-Poteshman 2009, Nagel 2012, Bollerslev et al. 2018.
**Result:** Real, deployable signal. Phase 2 results meet 7/8 hypothesis-doc pass criteria.
**Numbers (best config: formation=20, entry_z=1.0, exit_z=0.5, max_hold=10, atr_stop=1.5x, atr_tp=2.0x, per_trade_risk=0.5%):**
  - Full period D1 2021-05 to 2026-05 (5y): Sharpe **0.48**, total return +8.22%, max DD -5.38%, win rate 56.2%, profit factor 1.49, 73 trades. FTMO sim PASS clean.
  - Walk-forward OOS Window 1 (2024-05 to 2025-05): Sharpe **0.56**, +3.31% return, -5.38% DD, 53.3% win, PF 1.45, 30 trades. FTMO PASS.
  - Walk-forward OOS Window 2 (2025-05 to 2026-05): Sharpe **1.45**, +4.19% return, -3.68% DD, 66.7% win, PF 2.34, 18 trades. FTMO PASS.
  - **Mean OOS Sharpe 1.01** (vs IS 0.48). IS->OOS degradation -0.53 -- OOS is BETTER than IS. This is the inverse of overfitting and is a strong tell the signal is real.
  - Parameter sweep (18 cells): 16/18 positive Sharpe (89%), Sharpe std 0.18, all 18 FTMO PASS. Flat parameter surface -- not curve-fit.
**Why it (didn't) work:** Mean-reversion at the short-horizon index level is supported by multiple post-2009 academic studies and a clear flow-based mechanism. The 2026-05-11 lag-correlation test (all 36 cells negative across 4 indices) and bucket test (bottom decile +0.64-1.00% forward 5d, t-stats 2.3-3.2 on 3/4 symbols) confirmed the signal exists *before* building any strategy code. The strategy then realised this signal across a clean parameter surface with consistent FTMO compliance.
**Implication for future work:**
  - This is the first **deployable** strategy candidate in the repo. Next: re-run with live FTMO spreads (current cost model uses conservative 50-100 point estimates because the demo broker reports 0), then 4-week paper-trade run before any Challenge purchase.
  - The "trend filter" (200d EMA floor) is a no-op on this sample -- every cell identical on/off because all 4 indices stayed above EMA200 throughout 2021-2026. Keep it as a defensive guard for future bear-market regimes but do not rely on it for current performance.
  - The shorter-formation alternative (formation=5, entry_z=2.0) hits Sharpe 0.47 with PF 1.80 and 68% win rate -- worth holding as a backup config if the primary config degrades in live trading.
  - **Caveats before deployment:**
    - Only 2 OOS walk-forward windows (5y is a short sample for D1 strategy validation).
    - Spread assumption may be optimistic; real FTMO spreads need verification on a funded account.
    - The 2024-2026 sample is dominated by a single regime (post-COVID mean-reverting market). If regime shifts to persistent bear or persistent low-vol grind, mean-reversion can collapse.
    - Per-trade tail risk (mean-reversion fails violently in regime breaks): tight ATR stop is the only protection, must remain non-optional.

### 2026-05-11 -- Index Time-Series Momentum (US500, USTEC, US30, DE40) -- rejected at signal-decay stage
**Hypothesis tested:** Equity index CFDs exhibit positive return autocorrelation at 20-120d lags (Moskowitz, Ooi, Pedersen 2012); long the indices in their own uptrends, short in downtrends, vol-targeted sizing. Universe = 4 major USD/EUR-denominated indices on broker MetaQuotes-Demo (US500, USTEC, US30, DE40). 5y D1 (2021-05 to 2026-05; USTEC 3.8y).
**Result:** Rejected before backtesting -- signal-decay (autocorrelation) test fails the Phase 1 pass criterion.
**Numbers:**
  - Cross-universe average lag-k autocorrelation: lag-5 +0.028, lag-20 +0.010, lag-60 -0.005, lag-120 -0.002, lag-250 -0.005. Pass criterion was lag 20-120 average > 0.02 -- fails.
  - Past-formation -> forward-holding correlation across {20,60,120}d formation x {1,5,20}d holding: **all 36 cells negative** across all 4 symbols. P(all 36 < 0 | iid null) ~= 1.5e-11. Strongest signal: USTEC (120d formation, 20d forward) = -0.363.
  - Lag-1 raw autocorrelation negative on all 4 symbols (-0.013 to -0.061) -- short-term mean reversion is the dominant single-bar pattern.
**Why it (didn't) work:** The 2021-2026 sample is structurally mean-reverting at the index level, not momentum-driven. Three regimes contribute:
  1. 2022 bear (Fed hiking) followed sharply by 2023 recovery -- past-60d returns negative, future-60d positive.
  2. Post-COVID market structure (faster Fed responsiveness, options-flow / 0DTE gamma squeezes) accelerates mean-reversion at index level even when single-stock momentum still works.
  3. The MOP 2012 paper used 1965-2009 data (44 years) including multiple structural regimes. A 5-year sample dominated by post-COVID dynamics is too narrow to confirm the asset-class-wide TSMOM result.
**Implication for future work:**
  - Do NOT proceed to TSMOM backtest. The signal does not exist on this universe in this sample.
  - The empirical finding -- consistent negative formation-holding correlation -- is itself a tradeable hypothesis: **short-horizon mean-reversion at the index level**. This is supported by Lehmann (1990), Lo and MacKinlay (1990) for individual stocks, and post-2020 academic interest in dispersion / overnight reversal effects on indices. Worth a separate hypothesis doc and Phase 1 test if pursued.
  - Alternative pivots that have NOT yet been ruled out:
    - **FX carry** (interest-rate-differential signal -- different mechanism, different regime sensitivity from momentum). Same broker, same data layer.
    - **Index mean-reversion** at z>2 short-formation z-scores (the inverse of what was tested here, with statistical evidence from this very test).
    - **Volatility-regime / vol-carry** strategies on indices (sell vol when realized vol low, buy when high) -- different signal entirely.
  - **Process validation:** the Phase 1 signal-decay test caught this in ~10 minutes of compute, before building any strategy code. Per CLAUDE.md sec.4 Phase 1 step 4 -- this is exactly what that step is for. Always run it before committing to a backtest.

### 2026-05-11 -- FX Cross-Sectional Momentum (7 USD majors) -- killed
**Hypothesis tested:** Rank 7 USD-major FX pairs by 20-bar formation-period return (USD-base pairs inverted), z-score, long top / short bottom by z-score, with EMA(50) trend confirmation and a cross-sectional volatility regime filter. Sizing: 1/4 Kelly fractional, ATR(14)*1.5 stop, 0.5% per-trade risk. Reference: Menkhoff et al. (2012), Asness et al. (2013).
**Result:** Failed. No deployable edge.
**Numbers:**
  - Full period D1 (2021-05 to 2026-05, 5y): Sharpe -0.50, total return -15.3%, max DD -22.0%, win rate 37.8%, profit factor 0.84, 707 trades. FTMO sim FAIL (357 max-loss-line breaches).
  - Walk-forward OOS: -1.14 Sharpe (2024) / +0.04 Sharpe (2025). IS->OOS degradation +0.05 (so OOS is honest, just unprofitable).
  - 54-cell parameter sweep on D1 (formation in {16,20,24}, ema in {40,50,60}, z-thresh in {0.3,0.5,0.7}, trend-filter on/off): **0/54 cells positive Sharpe.** Best cell -0.31 Sharpe. Sharpe std 0.14 (filter on), 0.15 (filter off) -- surface is stable, this is NOT an overfitting artifact, the strategy is consistently losing.
  - 54-cell sweep on H4: catastrophically worse, Sharpe range -3.82 to -1.88, all cells near -100% drawdown. Transaction-cost drag (commission + spread + slippage on ~3000 trades over 3y) overwhelms any signal at H4 in this universe.
  - EMA trend-filter ablation: mean delta-Sharpe (off - on) = -0.11 on D1, -0.66 on H4 -- filter helps on net (it is doing real work). Removing it does not unlock edge.
**Why it (didn't) work:** Two compounding reasons.
  1. **Regime.** Academic FX-momentum Sharpe (Menkhoff 2012) was concentrated pre-2008. The 2010s+ regime (low rate dispersion, central-bank-driven currency moves, USD as dominant systematic factor) is unfavorable to momentum on majors. Breakeven on this setup needs win-rate > 1/(1+R) ~= 42%; we hit 37.8%, the ~4 percentage-point gap is consistent with the post-2008 momentum-decay literature.
  2. **Universe too narrow.** 7 pairs cross-sectionally is undersampled. The z-score normalisation amplifies idiosyncratic noise when the cross-section is small. Standard academic tests use 16-50 currencies.
**Implication for future work:**
  - Do NOT iterate further on this hypothesis with this universe at D1/H4. Parameter surface is honest and there is no hidden pocket of alpha.
  - If revisiting FX momentum: broader universe (G10 cross-rates -- 45 pairs), add carry overlay (long high-yielders, short low-yielders + momentum tilt), or move to short-horizon (M5-M30) where microstructure-driven momentum still has measurable edge.
  - More promising pivots within scope (FTMO + MT5):
    - **FX carry** (interest-rate-differential signal -- different mechanism, different regime sensitivity).
    - **Index momentum / breakout** on US500, NAS100, GER40 -- post-2010 equity momentum still has documented alpha and CFD spreads are tight on these.
    - **FX mean-reversion at extremes** (z > 2 in short formation windows -- opposite signal to momentum).
    - **Volatility regime / vol-of-vol** strategies.
  - **Infrastructure validated.** The PortfolioEngine, SharedSignalStore (no-look-ahead), walk-forward harness, FTMO simulator, and Kelly sizing all work and produce honest numbers. Reusable for the next hypothesis.

**Template:**
```
### YYYY-MM-DD — <signal or hypothesis name>
**Hypothesis tested:** ...
**Result:** Worked / didn't work / partial.
**Numbers:** Sharpe, hit rate, half-life, etc.
**Why it (didn't) work:** Mechanism in plain language.
**Implication for future work:** ...
```

---

### Backtest & Validation Findings

### 2026-05-11 -- Two latent sizing bugs caught only by running real-data Phase 2
**What happened:** First Phase 2 run produced 0 trades. Tracing showed `MomentumSizer.kelly_fraction(0.50, 1.0)` returns 0.0 at the breakeven priors (`full_kelly = W - (1-W)/R = 0`) -- there's no Kelly edge estimable yet, but returning 0 short-circuits all sizing. After patching that to fall back to `per_trade_risk_pct`, the second run produced 707 trades but with avg-win=$7 / avg-loss=$5 on a $100K account -- a clear "everything is at the broker minimum" signature.
**Root cause of the lot-sizing bug:** `pnl_per_lot_per_price_unit = contract_size * tick_value / point` is wrong. `tick_value` already encodes the per-lot account-currency value of one point; multiplying by `contract_size` again inflates `risk_per_lot` by ~1e5, which collapses `raw_lots` to 0 and the `min_lots = 0.01` floor takes over. Correct formula is just `tick_value / point`. (For EURUSD with tick_value=1.0 and point=1e-5: $1 / 0.00001 = $100,000 per lot per full price unit; a 1-pip move = 0.0001 * $100,000 = $10/lot. Matches `costs.py::SymbolSpec.pnl()`.)
**Validation that future-me should remember:** When `avg_loss` divided by `0.005 * equity` is roughly `1/100`, you are clipped to the 0.01-lot minimum and the sizing formula is the suspect. The 0.01-lot floor disguises sizing bugs because trades still happen and the equity curve still moves.
**Why the unit tests didn't catch it:** Test_fx_momentum tests sized lots in isolation with synthetic prices but never asserted on the absolute lot magnitude. Lesson: in sizing tests, assert `lots > min_lots` when risk budget is non-trivial.

### 2026-05-11 -- mt5.initialize() does NOT accept path=None
**Symptom:** `mt5.initialize(path=None)` throws "Invalid path argument" even with `path` being the parameter that should accept it.
**Fix:** Call `mt5.initialize(self._path) if self._path else mt5.initialize()` -- a bare call with no args is required when no terminal-path override is needed. The kwarg form with None is treated as an explicit positional value.

---

### Live / Paper Trading Observations

*No entries yet.*

**Template:**
```
### YYYY-MM-DD — <strategy> paper week <N>
**Period:** YYYY-MM-DD to YYYY-MM-DD
**Realized:** Sharpe X, return Y%, max DD Z%, N trades.
**Expected (from backtest):** Sharpe X', return Y', max DD Z'.
**Variance explanation:** Slippage / regime / signal degradation / other.
**Action:** Continue / iterate / kill.
```

---

## Gotchas & Pitfalls

### FTMO-Specific (highest priority — these blow the account)

**Reference:** FTMO Academy lessons linked in Reference Material above. **Re-verify rules before each Challenge purchase** — FTMO updates rules periodically.

- **The day rolls at 00:00 Europe/Prague, not UTC, not broker time.** Use `zoneinfo.ZoneInfo("Europe/Prague")` everywhere a "today" boundary matters. Brokers commonly run UTC+2/+3 server time year-round; that is a different clock from FTMO's accounting clock. Misalignment of ~1–3 hours is enough to fail an account when a position held into a "new day" by FTMO's clock counts toward the wrong day's loss budget.
- **Equity-based, not balance-based.** FTMO measures `balance + floating P&L + swaps − commissions`. A drawdown that's only floating (not yet realized) still counts. Bar-close monitoring of P&L is insufficient — use sub-second `account_info().equity` polling.
- **Tick-touch failure.** If equity *touches* the daily-loss line for one tick — even with no fill, even on a wick — the account fails. The system must operate at internal limits well below the FTMO line, with a `headroom_check` that simulates worst-case adverse fill before allowing the order.
- **Daily limit recalculates from previous-day midnight balance.** A profitable day raises tomorrow's limit; a losing day held overnight lowers it. Sleeping with a position open shifts your headroom across the boundary.
- **1-Step trailing max loss never decreases.** Once it ratchets up after a profitable end-of-day, it stays. Lock that high in state and don't recompute downward.
- **Best Day Rule (1-Step) is sneaky.** A bot can hit the profit target but fail at payout because one day's profit was >50% of total profitable-day profit. Track the ratio daily; throttle when it would project above 40% with the next trade's expected payoff.
- **News restriction (standard funded only).** No open OR close within ±2 minutes of high-impact news. The window applies to closes too — a bot that uses time-based exits can hit this. Either run on Swing accounts or load an economic calendar and route exits around the window.
- **No copy trading.** Running the same bot on multiple FTMO accounts is forbidden. One bot, one account. If you want to scale, parameterize each instance differently.
- **Funded account rules can differ from Challenge rules.** Re-read the rule set when transitioning from Verification to Funded; don't assume the configuration carries over.
- **The Challenge fee is a real cost.** Failing a $25K 2-Step burns ~€250. The bot must be tested to exhaustion on demo before paying for a Challenge.
- **MT5 terminal time vs. server time vs. Prague time — three clocks.** Be explicit which one is in use at every boundary. Tag every datetime in the codebase with its timezone; use `tzinfo`-aware datetimes everywhere; never naive `datetime.now()`.

---

### MT5-Specific

**Reference:** Official Python API docs at <https://www.mql5.com/en/docs/python_metatrader5>. Bookmark per-function pages — e.g. `/python_metatrader5/mt5ordersend_py` for `order_send` semantics.

**Install:** `pip install MetaTrader5`. Pin the version in `pyproject.toml`. Update with `pip install --upgrade MetaTrader5`.

**Hard requirements from the docs / ecosystem:**
- The `MetaTrader5` Python package only runs on **Windows**, and the MT5 terminal must be installed and reachable on the same machine. For Linux deployment, the standard workaround is running MT5 under Wine — log the deployment decision when made.
- `mt5.initialize()` must be called before any other function. `mt5.login(login, password, server)` is separate from `initialize()` and switches accounts on an already-initialized terminal.

**Pre-emptive gotchas (verified against the official reference):**
- **`mt5.last_error()` does not reset on read by guarantee, but it is overwritten by the next failing call.** Capture it immediately after any failure into a local variable; do not interleave any other MT5 calls before logging it.
- **`mt5.initialize()` is global state.** Calling it twice in the same process can cause silent state issues — wrap in a singleton client.
- **`mt5.order_send()` can return `None` on connection failure.** Always handle the `None` case before attribute access on the result.
- **`TRADE_RETCODE_DONE` is the success code for market/instant orders, but `TRADE_RETCODE_PLACED` is the success code for pending orders.** Check the right code for the order type.
- **`mt5.order_check()` is mandatory before `order_send()` in production paths.** It validates funds, stops level, and freeze level before the order hits the server. Skipping it is one of the most common sources of avoidable rejections.
- **`copy_rates_from_pos(symbol, timeframe, 0, count)` returns the most recent N bars including the in-progress (unclosed) bar at position 0.** Always drop or ignore the last bar if it is not closed, or you will leak future information into signals.
- **`copy_ticks_from` and `copy_ticks_range` require a `flags` argument** — `mt5.COPY_TICKS_ALL`, `mt5.COPY_TICKS_INFO`, or `mt5.COPY_TICKS_TRADE`. They are not optional.
- **`mt5.symbol_select(symbol, True)` may be required** before `copy_rates_*` or `copy_ticks_*` on a symbol that is not currently in MarketWatch. Some brokers/builds tolerate inactive symbols, others return empty arrays silently.
- **Symbol names vary by broker.** "EURUSD" on one broker is "EURUSD.r", "EURUSDx", or "EURUSD.pro" on another. Always resolve symbol names through `data/symbols.py` — never hardcode.
- **Server timezone is broker-specific.** Most brokers run UTC+2/+3 with DST. The Python API returns Unix timestamps in seconds (UTC), so internally store everything in UTC and convert only at display boundaries. Bars and ticks both have a `time` field in seconds since epoch.
- **`OrderRequest` requires the right `action` constant** — `TRADE_ACTION_DEAL` for market orders, `TRADE_ACTION_PENDING` for limit/stop orders, `TRADE_ACTION_SLTP` to modify stops on a position, `TRADE_ACTION_REMOVE` to cancel a pending order. Wrong action returns a non-obvious error.
- **`OrderRequest.type_filling` must match the symbol's allowed filling modes** (returned by `symbol_info().filling_mode`, a bitmask). Mismatches return `TRADE_RETCODE_INVALID_FILL`.
- **`positions_get()` and `orders_get()` return tuples, not lists, and return `None` on error** (not an empty tuple). Check for `None` before iterating.
- **For realized P&L reconciliation use `history_deals_get()`, not `history_orders_get()`.** Orders are intent; deals are executed fills. Net deal volume is the only ground truth for P&L.

---

### Python / Pandas Pitfalls

*Logging anticipated traps:*

- **`pd.read_parquet` with `pyarrow` engine returns nullable dtypes** that can break downstream `numpy` math. Cast explicitly when needed.
- **Resampling with `closed='right', label='right'` vs `'left'` is a frequent source of look-ahead.** Default to `closed='left', label='left'` for OHLC bars and document any exception.
- **`df.shift(1)` on multi-symbol panels** without grouping by symbol leaks across symbol boundaries. Always `.groupby('symbol').shift(1)`.

---

### Backtesting Pitfalls

*General quant traps that everyone hits eventually:*

- **In-sample peeking.** Once you look at OOS, that data is no longer OOS. Lock it. Literally name the file `OOS_LOCKED.parquet`.
- **Survivorship in the symbol universe.** Use point-in-time universes, not today's listings.
- **Selection bias from picking "best" parameters.** Always report the *distribution* of performance across parameter grids, not just the max.
- **Ignoring borrow / short availability.** Less relevant for FX/CFDs; very relevant for equity shorts. If extending to equities, model it.

---

## Open Questions

Living list of things we don't know yet. Move to the Decisions Log once resolved.

- [ ] Which Challenge type to start with: 1-Step (3% daily / 10% trailing / Best Day rule) vs. 2-Step (5% daily / 10% static, no Best Day). 2-Step has more daily headroom; 1-Step is faster and uses static if you treat the trailing carefully. Default lean: 2-Step for the first attempt — easier to absorb adverse vol days. Decide before Milestone 6.
- [ ] Which account size tier for the first Challenge. $10K is cheapest (€89-€155) but per-trade dollar risk is tiny. $25K (~€250) is a better learning-vs-cost tradeoff. $100K (~€540) only if confident in the bot's stability. Decide before Milestone 6.
- [ ] Standard vs. Swing account. Swing removes the news-window restriction and weekend-holding restriction at the cost of a fee uplift and slightly different conditions. If any strategy holds overnight or near macro events, Swing is mandatory. Decide as part of strategy selection in Milestone 5.
- [ ] Walk-forward window sizes — current tentative default is 12-month IS / 3-month OOS rolled monthly. Validate empirically once the first strategy is in place.
- [ ] Position sizing default — 0.5% per trade on a 1:2 R:R gives strong FTMO compliance margin but slow profit-target progress. 1% is the cap allowed by internal rules. Test sensitivity across the range.
- [ ] Equity-watcher poll frequency — 250ms default. Faster (100ms) is more conservative against tick-touch but increases CPU and MT5 API load. Decide before going live on a paid Challenge.
- [ ] Economic calendar source — ForexFactory weekly export (free, scrape-based) vs. Trading Economics API (paid, reliable) vs. FTMO's own calendar export. Decide before Milestone 4 news-blackout work.
- [ ] How to handle weekends and holidays in backtests — exclude entirely vs. carry positions with no P&L. Default: carry, no P&L assigned. For the FTMO simulator, model the Friday-close flat policy on standard accounts.
- [ ] Regime filter format — explicit threshold rules vs. learned classifier. Default: explicit thresholds for v1; learned classifier as a Milestone 7+ exploration.
- [ ] FTMO rule re-verification cadence — when to re-fetch the Academy pages and check for rule changes. Default: every 90 days, and immediately before any Challenge purchase. Track in a calendar reminder.

---

## Reference Material Used

When a paper, blog post, book chapter, or repo materially influenced a decision, log it here so future-you can re-find it.

### MetaTrader 5 Python Integration — Official Reference (MQL5.com)
**URL:** <https://www.mql5.com/en/docs/python_metatrader5>
**Used for:** Canonical function inventory in `CLAUDE.md` Section 5; gotchas in this file's MT5-Specific section; engineering requirements for `order_check`, `last_error`, `terminal_info().connected`, and tick `flags` argument.
**One-line summary:** Single source of truth for the `MetaTrader5` Python package — covers session, market data, pre-trade calc, execution, and history APIs.
**Quality:** Trusted (vendor reference). Read the per-function subpages (e.g. `/python_metatrader5/mt5ordersend_py`) for full parameter semantics — the index page only summarizes.

### FTMO Trading Objectives — Official Academy Documentation
**URLs:**
- Maximum Daily Loss: <https://academy.ftmo.com/lesson/maximum-daily-loss/>
- Maximum Loss: <https://academy.ftmo.com/lesson/maximum-loss/>
- Drawdown explainer: <https://ftmo.com/en/blog/drawdowns/>
- 1-Step rules incl. Best Day: <https://ftmo.oanda.com/how-to-pass-ftmo-challenge/>
**Used for:** All FTMO rule values in `CLAUDE.md` Section 3; the entire `risk/ftmo.py` rule machine; the FTMO simulator in `backtest/ftmo_sim.py`.
**One-line summary:** Authoritative spec of FTMO's daily-loss / max-loss / Best Day / news rules across 1-Step, 2-Step, and Funded variants.
**Quality:** Trusted (vendor reference). **Re-verify before purchasing each Challenge** — FTMO has changed rules historically (removed time limits in 2024, added 1-Step in 2024, etc.) and the bot's rule encoding must match the rules in force at the time of purchase. Cross-reference with the rules tab on FTMO's checkout page at the moment of signup.

---

## Glossary

Project-internal vocabulary. Add as the system grows so new sessions don't waste cycles re-deriving meaning.

**Trading & engine terms:**
- **Bar** — A single OHLCV candle at a given timeframe.
- **OOS lockbox** — The most recent ~20% of historical data, untouched until a strategy is otherwise frozen.
- **Pre-trade gate** — The risk function every order must pass before reaching `mt5.order_send()`.
- **Regime filter** — A function inside the strategy that returns `is_active=True/False` depending on current market conditions.
- **Slicer** — Execution component that breaks large orders into TWAP/VWAP child orders.

**FTMO terms (use these exact names — they map to FTMO's docs):**
- **Initial Sim Capital** — The starting balance of the FTMO sim account ($10K, $25K, $100K, $200K). All FTMO percentage rules are computed off this number.
- **Maximum Daily Loss (MDL)** — FTMO's daily-loss rule. 5% of Initial Sim Capital on 2-Step, 3% on 1-Step. Equity-based. Resets at 00:00 Europe/Prague.
- **Maximum Loss (ML)** — FTMO's total-loss rule. 10% of Initial Sim Capital. Static on Challenge; trailing-up only on Funded Rewards.
- **Daily Limit** — The actual account-currency level below which equity must not drop on a given Prague day. Computed as `previous_midnight_balance − MDL`.
- **Best Day** — On 1-Step, the day with the highest closed profit. Best Day's profit must be ≤ 50% of total profitable-day closed profit at payout.
- **Headroom** — The dollar distance between current equity and the nearest FTMO line. Tracked continuously; `headroom_check` is the gate that uses it.
- **Internal kill** — The bot's self-imposed shutdown at a level well above (better than) the FTMO line. The first line of defense. FTMO rule violation should never happen because internal kill fires first.
- **FTMO Imminent** — Warning state when equity is within 0.5% of an FTMO line. Triggers alerts and reduces sizing, but is not yet an internal kill.
- **Tick-touch failure** — FTMO failure mode where equity touches a limit on a single tick (often a wick) and the account is failed even though equity recovers seconds later.

---

## Session Handoff Notes

When ending a coding session in a non-obvious state (mid-refactor, half-finished feature, hypothesis being tested), leave a note here so the next session resumes cleanly. **Delete entries once the next session resolves them.**

*No entries yet.*

**Template:**
```
### YYYY-MM-DD — <handoff title>
**Where I left off:** ...
**Next concrete step:** ...
**Watch out for:** ...
```
