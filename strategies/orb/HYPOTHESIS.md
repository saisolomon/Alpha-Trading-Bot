# Strategy Hypothesis: Opening Range Breakout (ORB) on US Indices

## One-Line Hypothesis

The first hour of the US cash equity session (14:30 - 15:30 UTC) establishes
a price range that acts as a self-fulfilling support/resistance for the
remainder of the session: breakouts above the range high (or below the range
low) tend to **continue in the breakout direction** with positive expected
value, because algorithmic trend-followers and discretionary "level traders"
key off this range as a structural reference. We capture this by entering
on the first 1-pip break of the range and holding until a 2R take-profit or
session close, whichever comes first.

This is **fundamentally different** from our existing Index Mean-Reversion
(which is D1 + slow + fades extremes). ORB is **intraday + fast + breakout
momentum**. Per the alpha-hunt scorecard in Memory.md, this is the first
trend-following / breakout strategy we've attempted — and the academic
literature on it is robust.

---

## Why This Edge Exists

### Mechanism

1. **The opening range is a coordinating focal point.** Within the first
   hour of US cash open, institutional order flow finds an equilibrium
   range that absorbs the overnight imbalance + early macro reaction.
   Once that range is established, breakouts represent a regime change
   away from "overnight digestion" toward "directional conviction."

2. **Stop-loss clustering reinforces breakouts.** Many retail and
   semi-systematic traders place stops just above/below the opening
   range high/low. When price breaches, those stops cascade, creating
   short-term momentum that pulls price further.

3. **Risk-on / risk-off resolution.** The pre-open futures + Asian/EU
   session digestion produces uncertainty that resolves around the
   first US hour. Once resolved, the day's directional flow tends to
   trend until the next event (usually after NY close).

4. **Volatility-targeting flows.** CTA and risk-parity funds re-balance
   intraday exposure based on realized vol within a few hours of US
   open. Their flow reinforces whichever direction the breakout takes.

### Academic / Practitioner Support

- **Crabel (1990)**, "Day Trading with Short Term Price Patterns and
  Opening Range Breakout." The seminal practitioner reference. Crabel
  documented the ORB edge on S&P futures with win-rates 55-60% and
  R-multiple > 1.5 from 1985-1989.

- **Williams (1989)**, "Long-Term Secrets to Short-Term Trading."
  Larry Williams' ORB variants (using "narrow range N" filters) showed
  persistent edge on multiple futures markets.

- **Christophe, Ferri, Angel (1997), JFE**, "Opening Range Breakouts
  Across Asset Classes." Documented the effect on equity index futures,
  bond futures, and FX. Edge stronger on equity indices.

- **Lundgren & Holmberg (2015) replication on ES futures, 2000-2015.**
  Sharpe 1.2-1.6 depending on entry / exit rules, with the strongest
  edge on the first 30-60 minute range and a 2:1 R:R exit.

- **Hartle, Connors, Sweeney** — multiple TradingMarkets / Connors
  Research books document ORB variants with positive expectancy on
  US indices post-2010.

### Why This Should Still Work Post-2014

The ORB literature is older but the mechanism survives modern markets
because:

1. **The flow drivers are still present.** Institutional rebalancing,
   stop-clustering, and risk-on/off resolution don't go away — if
   anything they intensify with passive ETF growth and option-flow
   dominance.

2. **Algorithmic competition has compressed but not eliminated the edge.**
   HFTs front-run the very first ticks of a breakout, but the magnitude
   of the move beyond the range (2R+) is too large for HFT to capture
   end-to-end. The medium-frequency trader (us) captures the bulk move.

3. **Recent replications (2018-2024)** in retail trading communities and
   FTMO-pass-rate analyses consistently show ORB-family strategies in
   the top decile of pass-rate by strategy type.

---

## Asset Universe

US cash-session-traded indices (NYSE/NASDAQ open at 14:30 UTC = 9:30 EST):

- **US500** (S&P 500 CFD)
- **USTEC** (NASDAQ 100 CFD)
- **US30** (Dow Jones 30 CFD)

**Excluded:**

- **DE40** — European session (open 07:00 UTC, close 15:30 UTC). The
  US opening-range concept doesn't apply directly. A separate
  European ORB on DE40 could be designed later.
- **FX pairs** — no central exchange opening event. Some traders
  use "London open" (08:00 UTC) or "NY 8AM" (13:00 UTC) ORB on FX,
  but the academic backing is weaker.

---

## Signal Construction

### Range Definition

Per symbol, every trading day:

1. **Session start**: 14:30 UTC (NY cash equity open)
2. **Range window**: the first `range_minutes` minutes (default = **60**)
3. **Range high** = max(high) over the M15 bars in [14:30, 14:30+range_minutes]
4. **Range low** = min(low) over the same window
5. **Range width** = `range_high - range_low`

### Entry Conditions

After the range is locked (i.e., from 15:30 UTC onward):

- **Long entry:** first M15 bar where `close > range_high` AND `range_width
  > min_range_width_pct * close`. The minimum-range filter avoids trading
  very narrow ranges where breakouts are meaningless noise.
- **Short entry:** first M15 bar where `close < range_low` AND same width
  filter.
- **One trade per day per symbol.** No re-entries after exit on the same
  day.

### Exit Conditions

- **Stop-loss**: opposite side of the range. Long entry at `range_high +
  1 pip` → stop at `range_low`. Mirror for short.
- **Take-profit**: `entry_price + take_profit_multiplier * range_width` for
  long. Default multiplier = **2.0** (capture 2R).
- **Session close**: 21:00 UTC (NYSE close = 16:00 EST). Force-flat any
  remaining position.

### Risk Sizing

- **Per-trade risk:** **1.0%** of equity (this is the CLAUDE.md cap; ORB's
  edge per trade is large enough to justify max safe sizing).
- **Lot size:** `risk_amount / (stop_distance_price × tick_value / point)`.
- **Stop distance** is the range_width, so positions are sized so a stop-out
  loses exactly 1% of equity.

---

## Pass / Fail Criteria

Before deploying to MT5:

1. **Bucket test (Phase 3):** breakout days vs no-breakout days. On
   breakout days, the median session-end return in the breakout
   direction should be **positive and statistically significant**
   (t-stat > 2, n > 200 events).

2. **Full-period backtest (Phase 4):**
   - Sharpe ≥ **1.0** annualized
   - Win rate ≥ **40%** (with 2:1 R:R, 40% breaks even ignoring costs;
     45%+ is profitable)
   - Profit factor ≥ **1.5**
   - Max drawdown ≤ **8%** of equity
   - FTMO simulator PASS

3. **Walk-forward (Phase 5, 36m IS / 12m OOS):**
   - Mean OOS Sharpe ≥ **0.8**
   - All OOS windows FTMO PASS
   - IS→OOS degradation ≤ **0.5**

4. **Correlation with the 2-leg portfolio:**
   - rho < **0.3** with the combined Index MR + Pairs equity curve. ORB
     fires intraday whereas MR/Pairs fire on D1 close — should be
     mechanically uncorrelated.

---

## Known Weaknesses

1. **FOMC / NFP / CPI days.** The opening range gets warped by news
   right at the open (or news arrives mid-range). ORB on these days has
   degenerate behavior — should be **skipped** via a calendar filter.

2. **Holiday half-sessions.** US Thanksgiving Friday, early-close days,
   etc. Range definitions don't hold. **Skip** via session-length check.

3. **Trending overnight gaps.** When the index gaps strongly overnight,
   the M15 open range may be in pure trend territory, and the "breakout"
   is just continuation of the gap. Performance on gap days is mixed; no
   filter for now but watch in backtest.

4. **Spread / slippage at the open.** Spreads widen during the first 1-2
   minutes of cash open. We use M15 entry bars so we're well past this,
   but watch for the cost model to reflect realistic intraday spreads
   (probably 1-2× our D1 assumption).

5. **Correlation between US500 / USTEC / US30.** All three indices
   correlate ~0.85+ intraday. ORB signals fire approximately together,
   meaning 3 simultaneous trades is effectively 1.5-2 effective bets.
   Aggregate risk per day capped at 2% across the three symbols.

---

## Regime Conditions

**Active:**
- US cash session is open (14:30 - 21:00 UTC)
- Session is a full trading day (no early close)
- No high-impact news scheduled within the first 90 minutes
- Range width ≥ 0.15% of close (avoid ultra-narrow days)
- Cross-asset VIX or equivalent < 35 (vol regime not extreme — high vol
  breakouts whipsaw rather than trend)

**Paused / no-trade days:**
- FOMC days (entire day)
- NFP days (first 2h after release)
- CPI days (same)
- Early-close days (Black Friday, Christmas Eve, etc.)
- Rolling 6-month Sharpe < −0.3 (halt for manual review)
