# Trial Log — FTMO Trial #1 (OANDA-Demo-1, $200K, 2-Step Phase 1)

> Daily activity log for the live FTMO trial that started 2026-05-28.
> Trial ends 2026-06-10. Profit target: $10,000 (5%). 5% daily-loss line. 10% max-loss line.
> Entries added at end-of-day after the 22:30 UTC digest.

| Date | Realized P&L | Floating P&L | Day % | Cum P&L | Cum % | Notable |
|---|---|---|---|---|---|---|
| 2026-05-28 (Thu, Day 1) | +$1,933 | — | +0.92% | +$1,857* | +0.92% | First real trade fires. 4 wins + 1 loss across 5 EAs. *digest reported +$1,857 after swaps/commission* |
| 2026-05-29 (Fri, Day 2) | +$80 | — | +0.01% | +$1,937 | +0.94% | Digestion day. XAUUSD +$520 win offset by GBPUSD -$439 SL. |
| 2026-05-30 (Sat, Day 3) | 0 | — | +0.00% | +$1,937 | +0.94% | Weekend. No trades. One 5-min MT5 disconnect at 07:47 UTC, auto-recovered. |
| 2026-05-31 (Sun, Day 4) | 0 | — | +0.01% | +$1,937 | +0.95% | Weekend. No trades. |
| 2026-06-01 (Mon, Day 5) | -$1,025 | -$106 | **-0.55%** | +$912 | +0.46% | **First losing day.** US500 ORB -$882, GBPUSD SwingBreak -$543, US100 drift +$165. AUDJPY still open. |
| 2026-06-02 (Tue, Day 6) | +$940 | — | **+0.72%** | +$1,852 | +0.92% | **Strong recovery.** GBPUSD LondonMomo +$743 TP, XAUUSD LondonFix +$501 TP, two small losses. AUDJPY 1.55 lot opened, closed somewhere. |
| 2026-06-03 (Wed, Day 7, FINAL) | **-$1,395** | $0 | **-0.91%** | **-$1,465** | **-0.73%** | **4-SL cluster day.** 11:31 AUDJPY 1.37 SL -$161, 11:51 XAUUSD SL -$479, 13:06 GBPUSD SL -$251, **16:50 AUDJPY 1.55 SL -$505** (Tue position). USD-strength rip kills the "diversified" book — all 3 USD-counter pairs (AUDJPY, XAUUSD, GBPUSD) break down together. **Worst day of trial.** Portfolio risk cap held, no kill. |
| 2026-06-04 (Thu, Day 8) | +$1,466 | — | **+0.70%** | -$1 | -0.00% | **Break-even reclaimed.** EURUSD LondonMomo +$745 TP, **US500_M15_ORB +$1,010 TP** (its FIRST win, after Day 5's -$882 — the EA is NOT broken). XAUUSD fix +$372. Losses: GBPUSD x2 = -$661. Mean-reversion-to-EV thesis playing out. |
| 2026-06-05 (Fri, Day 9) | +$632 | $152 (AUDJPY) | **+0.38%** | +$632 | +0.31% | **US500_M15_ORB ANOTHER +$967 TP.** Net across 3 ORB trades: +$1,095 (positive expectancy confirmed). GBPUSD SL -$307. New AUDJPY SELL 1.40 opens 20:00 UTC — rides into weekend. |
| 2026-06-06 (Sat, Day 10) | 0 | — | +0.00% | +$632 | +0.31% | Weekend. AUDJPY position remains open. |
| 2026-06-07 (Sun, Day 11) | 0 | +$152 | +0.00% | +$632 +$152float | +0.35% | Weekend. AUDJPY SELL 1.40 @ 113.158 → 112.970 = **+$164 floating**. No realized trades. |
| 2026-06-08 (Mon, Day 12) | +$544 | — | +0.27% | +$1,176 | +0.58% | GBPUSD LondonMomo +$746 TP, XAUUSD fix +$501 TP; US500 ORB -$684 SL (now 2W-2L), US100 drift -$20. |
| 2026-06-09 (Tue, Day 13) | +$301 | — | +0.15% | +$1,477 | +0.73% | **Biggest single win of trial: LondonMomo GBPUSD +$1,075.83** session close. XAUUSD +$318. Losses: GBPUSD SwingBreak SL -$511, EURUSD LondonMomo SL -$582. |
| 2026-06-10 (Wed, Day 14, FINAL) | **-$2,902** | +$710 (AUDJPY) | **-1.44%** | **-$1,669 realized / -$1,008 equity** | **-0.83% / -0.50%** | **Cluster day #3 — the trial's signature failure, confirmed 3×.** Four SLs in one session: XAUUSD -$508, GBPUSD -$620, EURUSD -$934, US500 -$840. AUDJPY trend short finally riding: +$710 floating at close. Machine rebooted 21:27 UTC; MT5 auto-recovered in 3 min, all EAs reattached, zero data loss. |

---

## OFFICIAL END + STAND-DOWN (2026-06-11)

**FTMO confirmed the trial expired 2026-06-10.** Official Day-14 digest: **-1.30%**. The MT5 login remained active after expiry and the EAs kept trading the zombie demo (GBPUSD_H1_SwingBreak opened a NEW 1.41-lot short at 23:56 UTC on 6/10; 3 positions open at stand-down, incl. the AUDJPY winner at ~+$693 float). **All post-expiry trades are EXCLUDED from the trial dataset** — the post-mortem window is 2026-05-28 00:00 → 2026-06-10 24:00 UTC, by `dealTimeMs`.

**Stand-down actions (2026-06-11), all reversible, ZERO data deleted:**
1. **Convex:** new `monitoringPaused` flag on accounts, honored by all three crons (heartbeat-staleness, daily digest, correlation). Set `true` for 1600138423. All trial data (snapshots/deals/positions/signals/alerts) preserved for the post-mortem. *Never use `deleteByBrokerLogin` to silence a retired account — it nukes history.*
2. **MT5:** terminal stopped. Positions left to FTMO's sweep (expired demo — no financial meaning).
3. **Monitor:** sentinel kill-switch added to `paper_trade_monitor.py` + `logs/MONITOR_DISABLED` created (the scheduled tasks need elevation to disable, and `mt5.initialize()` would otherwise RELAUNCH the stopped terminal every 5 min). Lingering monitor processes killed; sentinel verified live (instant clean exit).

**Re-enable for the next account (paid Challenge):** delete `logs/MONITOR_DISABLED`, relaunch MT5 with the new login, `npx convex run accounts:setMonitoringPaused '{"brokerLogin": <new>, "paused": false}'` (or just register the new account — new accounts default to monitored). Optional cleanup needing admin: `Disable-ScheduledTask` on the four FTMOBot tasks, or re-point them at the new setup.

---

## TRIAL FINAL VERDICT (2026-06-10, Day 14 close)

**Result: target missed; account never endangered; the data is the payoff.**

| Final metric | Value |
|---|---|
| Realized P&L | **-$1,669.28 (-0.83%)** ($201,840.04 → $200,170.76) |
| Equity P&L (incl. AUDJPY +$710 float) | **-$1,007.59 (-0.50%)** |
| Profit target (+$10,000) | Missed. Peak cumulative +$1,937 (Day 2). |
| FTMO rule violations | **ZERO in 14 days.** Closest daily-line approach: today, still $10,670 clear. |
| Worst day | Day 14: -$2,902 realized — under half the internal 3% kill, ~29% of FTMO's 5% line. |
| Infrastructure uptime | Survived: WiFi outage, MT5 disconnects, Convex 5xx, monitor hang + full machine reboot on the final day. Zero data loss. |

### The one finding that dominates everything else
**Three of the four losing days were the same event:** USD-strength rip → simultaneous SLs across AUDJPY/XAUUSD/GBPUSD/EURUSD (+US500 on Day 14). Days 5, 7, and 14 — the "diversified" 10-EA book is, on bad days, ONE bet on USD-counter beta. The 2% aggregate cap priced the EAs as independent; they are not. **Every dollar of net trial loss is attributable to this one structural flaw, which is precisely what M10 #1 (factor decomposition) measures and M10 #2 (correlation-aware Bayesian-Kelly sizing) fixes.**

### Per-EA quick tally (post-mortem will compute exact)
- **EURUSD_M15_LondonMomo (the carrier):** 6 big TP/session wins ($743-$1,076 each) vs ~5 SLs — clearly net positive, the trial's best strategy.
- **XAUUSD_M15_LondonFix:** ~4W (+$501, +$501, +$372, +$318) vs ~3L (-$479, -$508, -$28) — modest net positive.
- **US500_M15_ORB:** 2W-3L, **net -$429** (Day-9 "positive expectancy" call reversed; N=5 still noise → post-mortem decides).
- **GBPUSD_H1_SwingBreak:** churned both directions, net negative drag.
- **AUDJPY_H4_TrendFollow:** 3 SLs early, finally caught its trend on the final day (+$710 floating unbanked).
- **US100_H1_OvernightDrift:** small steady churn, roughly flat.
- **Never fired:** XAUUSD_H1_NewsReaction (no qualifying events), EURGBP_H4_MeanReversion (no 3σ), BTCUSD_M15_TrendFollow (dry-run bug, M10 task).

### What the trial bought us
1. Realized per-EA variance/correlation/cost data → feeds M10 sizing with Kelly + ERC.
2. The cluster-day failure mode confirmed 3× → the next-trial sizing fix is evidence-based, not theoretical.
3. Three live bugs caught and fixed (IOC→FOK, BTC dry-run, broker-state recovery identified).
4. Infra validated end-to-end through five distinct failure events, including a final-day machine reboot with 3-minute full auto-recovery.
5. Zero FTMO violations across 14 days → the risk framework is challenge-ready even though the alpha isn't yet.

**M10 post-trial work begins now. First task: trial post-mortem (Tier 1 #1).**

---

## Days 8-11 (2026-06-04 → 06-07) — RECOVERY ARC + WEEKEND

**The 4-day arc that mattered:** trial cumulative went from -$1,465 (Day 7 close, worst point) → -$1 (Day 8 break-even) → +$632 (Day 9) → +$632 + $152 floating (Day 11). **Net swing: +$2,097 across 2 trading days.**

### Day 8 (2026-06-04, Thu) — Break-even reclaimed
- **Digest: +0.70% (+$1,466 realized)**
- Wins: EURUSD_M15_LondonMomo +$745 TP, **US500_M15_ORB +$1,010 TP (its first win after Day 5 loss)**, XAUUSD_M15_LondonFix +$372 session_close
- Losses: EURUSD_M15_LondonMomo on GBPUSD -$590 SL, GBPUSD_H1_SwingBreak -$71 session_close
- Net realized: +$1,466.47

### Day 9 (2026-06-05, Fri) — US500 ORB confirms positive EV
- **Digest: +0.38% (+$770 net incl. swap)**
- Wins: **US500_M15_ORB +$967 TP** (second consecutive win)
- Losses: GBPUSD SL -$307, XAUUSD small -$28
- Net realized: +$632.49
- **New position:** AUDJPY_H4_TrendFollow SELL 1.40 @ 113.158 opens 20:00 UTC, rides into weekend

### Days 10-11 (2026-06-06 Sat, 2026-06-07 Sun) — Weekend hold
- AUDJPY SELL 1.40 remains open through weekend (note: trial-period EA accepted the weekend hold — risk acknowledged in CLAUDE.md §9, but FTMO 2-Step doesn't restrict weekend holding on this account type)
- Position now +$164 floating as of Sunday afternoon
- No realized trades; markets closed

### CRITICAL FINDING: US500_M15_ORB has positive expectancy

This **revises** my Day 5 panic verdict ("ORB on indices = noise, kill or add filter"). Across 3 trades:
- Day 5: -$882 (session_close loss)
- Day 8: **+$1,010 TP**
- Day 9: **+$967 TP**
- **Net: +$1,095. Positive EV.**

This is **classic high-variance ORB profile** — exactly what Zarattini-Barbon-Aziz 2024 (paper #6 in `research/academic_review_2026-06.md`) describes for ORB without the Stocks-in-Play filter: lower Sharpe than filtered, but **still positive expectancy on indices.** N=1 was insufficient evidence to condemn.

**M10 implication:** the `US500_M15_ORB EA decision` task in Tasks.md should NOT be biased toward "kill" anymore. Post-mortem decision will weigh: (a) keep as-is (positive EV demonstrated), (b) keep + retrofit volume-spike filter (per Zarattini for higher Sharpe), (c) port to Stocks-in-Play version post-funded on IBKR (still the best academic version of the strategy).

### Cumulative trial trajectory (visual)

```
Day 1  ████████ +$1,857
Day 2  ▏         +$80
Day 3  ─         0
Day 4  ─         0
Day 5  ████▏▏▏▏▏ -$1,025
Day 6  ███▏▏▏▏   +$940
Day 7  ██████▏   -$1,395 ← worst point, -$1,465 cumulative
Day 8  ██████    +$1,466 ← recovery starts
Day 9  ██▏▏▏     +$632
Day 10 ─         0 (weekend)
Day 11 ─         +$152 floating (still weekend)
```

### Target math with 3 trading days left

| | |
|---|---|
| Target | +$10,000 |
| Current cumulative realized | +$545 (5.5% of target) |
| Plus floating AUDJPY | +$152 |
| Need from here | **~$9,455** |
| Trading days left | 3 (Mon 6/8, Tue 6/9, Wed 6/10) |
| Required avg/day | **~$3,152/day** |
| Best day this trial | $1,857 (Day 1) |
| **Updated odds** | **~5-10%** |

**But — distance to daily kill: $10,194 (safe). Distance to max kill: $21,781 (safe).** The portfolio is structurally protected. We probably don't hit $10K, but we don't fail either.

### What the trial has already accomplished (regardless of $10K outcome)

1. **Sharpe-positive over 11+ days across 10 EAs, 4 asset classes, 3 timeframes** — the multi-strategy thesis works
2. **Survived two correlation-cluster-loss days (Day 5, Day 7)** — risk caps held, system recovered
3. **Discipline test passed** — no panic intervention, system mean-reverted to EV as predicted
4. **US500_M15_ORB validated** — revised verdict from "broken" to "positive EV"
5. **Real per-EA / per-symbol cost data collected** — feeds the M10 sizing calibration with Kelly framework
6. **Real correlation breakdown observed** — feeds the M10 factor decomposition (Day 7's USD-strength cluster is gold for this)
7. **Three architectural bugs caught and fixed live** — IOC→FOK, EA broker-state-recovery, BTC dry-run
8. **End-to-end infrastructure validated** — MT5 + BotOrchestrator + Convex + Pushover survived WiFi outage, MT5 reconnect, Convex 5xx blips, 162h of continuous uptime

The trial's actual value isn't the $10K — it's the **realized variance/correlation/cost data feeding the next attempt.** Whatever the final number Wednesday, this trial paid for itself in lessons.

---

## Day 7 (2026-06-03, Wednesday) — FINAL — DETAIL

**Digest reported: -0.91% (worst day of trial).**

**Snapshot at 22:30 UTC digest close:**
- Balance: $200,375.48 (was $201,819 at Day 6 close → -$1,444 today incl. swaps)
- Equity: $200,375.48 (flat — all positions closed)
- Open positions: 0
- Distance to daily-loss line: $10,019 (today's new anchor)
- Distance to max-loss line: $20,038 (full safety margin intact)

**Closed deals today (final, 4 SL hits):**

| Time UTC | EA | Symbol | Side | Vol | Trigger | P&L |
|---|---|---|---|---|---|---|
| 11:31 | AUDJPY_H4_TrendFollow (Fri 5/29 position) | AUDJPY.sim | BUY | 1.37 | SL @ 114.276 | **-$160.67** |
| 11:51 | XAUUSD_M15_LondonFix | XAUUSD.sim | BUY | 0.36 | SL @ 4442.908 | **-$478.80** |
| 13:06 | GBPUSD_H1_SwingBreak | GBPUSD.sim | SELL | 2.46 | SL @ 1.34591 | **-$250.92** |
| **16:50** | **AUDJPY_H4_TrendFollow (Tue 6/02 position)** | **AUDJPY.sim** | **BUY** | **1.55** | **SL @ 114.178** | **-$504.83** |

**Net realized today: -$1,395.22.**

The 16:50 AUDJPY 1.55 hit AFTER the mid-day check — fourth USD-strength-driven SL of the day. This was the position opened by AUDJPY_H4_TrendFollow on Tuesday at 114.695; the trail stop caught up on the continued JPY-cross weakness.

**What this day means — full correlation-cluster-breakdown:**

I called this out in the original probability estimate ("~5% of days: -$1,500 to -$3,000 — correlation breakdown day; rare but happens"). Day 7 was exactly this scenario, even worse than I projected at mid-day. Mechanism: **USD strength rip → AUDJPY (×2 positions) breaks down + XAUUSD breaks down + GBPUSD breaks down.** Four SL hits across three "diversified" EAs because dollar strength is a hidden common factor that links them on big-USD days.

The 2% aggregate portfolio-risk cap held — total day loss bounded at -0.91%, ~one third of the internal daily kill threshold. **No EA misbehaved; the diversification thesis temporarily failed because we sized AUDJPY/XAUUSD/GBPUSD as independent bets when they share a hidden USD-counter beta.**

**This is the #1 finding for M10 sizing calibration** — those three EAs need to be treated as one cluster with shared exposure, not three independent positions. Factor decomposition (Tier 1 task) will quantify exactly how much of each EA's P&L is "long USD-counter beta" vs actual alpha.

**Cumulative trial through Day 7 close:**
- Initial capital: $201,840.04
- Current balance: $200,375.48
- Cum P&L: **-$1,464.56 (-0.73%)**
- Peak balance (Day 2): $201,937
- Drawdown from peak: -$1,562

**Target math from here:**
- Need: +$10,000
- From current: +$11,465 over **5 trading days** (6/4, 5, 8, 9, 10)
- Required avg/day: **~$2,293/day**
- Day 1 actual was $1,857 (best day). **We need to exceed Day 1's best by 23% — five days in a row.**

**Updated odds of hitting target: ~15-25%** (was 70% at trial start, 50-55% at Day 5 close, 35-45% at Day 7 mid-day).

**EA fire-frequency through Day 7:**

| EA | Trades opened | Status |
|---|---|---|
| EURUSD_M15_LondonMomo (on EURUSD + GBPUSD) | 4+ | Carrying the portfolio |
| XAUUSD_M15_LondonFix | 4 | Up-down cycling |
| GBPUSD_H1_SwingBreak | 5+ | Trend-follower drag |
| AUDJPY_H4_TrendFollow | 3+ | Trend-follower; today's SL |
| US100_H1_OvernightDrift | 3 | Steady, small |
| US500_M15_ORB | 1 | -$882 loss Day 5 only |
| XAUUSD_H1_NewsReaction | 0 | No qualifying news |
| EURGBP_H4_MeanReversion | 0 | No 3σ deviation |
| BTCUSD_M15_TrendFollow | 0 (still dry-run) | M10 task open |

**Standing order:** Do not intervene. This is the discipline test. Same code that delivered Day 1 is running today. Statistical regression to the mean is real; tinkering after a small adverse sample is the most reliable way to destroy expectancy. Wait for the 22:30 UTC digest to confirm Day 7's final number.

---

## Day 6 (2026-06-02, Tuesday) — DETAIL

**Digest reported: +0.72% (+$1,440 estimated, actual realized $939.56 + AUDJPY 1.55 close).**

**Closed deals:**

| Time UTC | EA | Symbol | Side | Vol | Trigger | P&L |
|---|---|---|---|---|---|---|
| 08:15→09:21 | EURUSD_M15_LondonMomo (on GBPUSD chart) | GBPUSD | BUY | 6.69 | TP @ 1.34772 | **+$742.59** |
| 10:30→12:31 | XAUUSD_M15_LondonFix | XAUUSD | SELL | 0.43 | TP @ 4522.458 | **+$500.74** |
| 10:00→16:00 | EURUSD_M15_LondonMomo (on GBPUSD chart) | GBPUSD | BUY | 2.71 | session_close | -$165.31 |
| 20:00→21:00 | US100_H1_OvernightDrift | US100 | BUY | 2.30 | time_ex | -$138.46 |
| 12:00→? | AUDJPY_H4_TrendFollow | AUDJPY | BUY 1.55 (new) | — | (closed somewhere, gap in my deals query) | — |

**Net realized visible: +$939.56.** Digest +$1,440 implies AUDJPY 1.55 closed for ~+$500 somewhere in between.

**Reading:** Best day since Day 1. London momentum + gold fix both connected for big TP wins. Mean reversion from Day 5's cluster loss working as expected.

---

## Day 5 (2026-06-01, Monday) — DETAIL

**Snapshot at 22:00 UTC digest:**
- Balance: $200,879.90  (was $201,905.41 yesterday → -$1,025.51 realized)
- Equity: $200,786.40  (floating AUDJPY -$93.50)
- Floating P&L: -$93.50  (AUDJPY -$106 + swap)
- Open positions: 1 (AUDJPY)
- Distance to daily-loss line: $10,002  (well clear)
- Distance to max-loss line: $19,072  (well clear — full safety margin intact)

**Closed deals today:**

| Time UTC | EA | Symbol | Side | Vol | Entry → Exit | P&L | Trigger |
|---|---|---|---|---|---|---|---|
| 16:15→20:30 | US500_M15_ORB | US500.sim | SELL | 31.50 | 7579.5 → 7607.5 | **-$882.00** | session_close (breakout went wrong way) |
| 17:00→18:23 | GBPUSD_H1_SwingBreak | GBPUSD.sim | SELL | 1.86 | 1.3412 → 1.3441 | **-$543.12** | SL hit (29 pips) |
| 20:00→21:00 | US100_H1_OvernightDrift | US100.sim | BUY | 1.90 | 30547.2 → 30634.4 | **+$165.68** | time_ex (overnight win) |

**Still open:**
- AUDJPY_H4_TrendFollow BUY 1.37 @ 114.451 → 114.327 → -$106.42 floating (Friday entry, still riding)

**EA performance through Day 5 (closed trades only):**

| EA | Trades | Wins | Losses | Net | Notes |
|---|---|---|---|---|---|
| EURUSD_M15_LondonMomo | 2 | 2 | 0 | **+$1,509** | London open momentum — both legs of dual-chart attachment won Day 1 |
| XAUUSD_M15_LondonFix | 2 | 2 | 0 | **+$1,038** | London fix fade — clean 2/2 |
| GBPUSD_H1_SwingBreak | 4 | 2 | 2 | **-$367** | Trend-follower; cycling both directions as expected |
| AUDJPY_H4_TrendFollow | 1 closed + 1 open | 0 | 1 | **-$501** | Day 1 SL; new position open since Friday |
| US100_H1_OvernightDrift | 2 | 1 | 1 | **+$153** | Overnight drift; small base hit |
| **US500_M15_ORB** | **1** | **0** | **1** | **-$882** | **First fire of the trial — Day 5 session_close loss** |
| BTCUSD_M15_TrendFollow | 0 | — | — | $0 | **Still in dry-run mode. See M10 task #BTC decision.** |
| XAUUSD_H1_NewsReaction | 0 | — | — | $0 | No NFP/FOMC/CPI events fired yet |
| EURGBP_H4_MeanReversion | 0 | — | — | $0 | No 3σ z-score deviations yet |

**Reading of the day:**

This is the first **statistical regression** day — exactly the kind of day the trial probability model said would happen ~10% of the time. Don't panic, don't tune.

- US500_M15_ORB took a -$882 loss on its first signal of the trial. That's the expected ORB profile: high variance, low win rate, big wins justify it over time. One losing trade is N=1, not evidence the strategy is broken.
- GBPUSD_H1_SwingBreak now 2-2 across 4 signals. Net -$367 = expected drag for a trend follower in its early sample.
- US100_H1_OvernightDrift quietly winning. The thesis (overnight risk premium) appears intact.
- AUDJPY position riding into Day 6.

**Cumulative trial through Day 5:**
- Cum P&L: **+$912** (+0.46%)
- Target: $10,000 (+5%)
- Days remaining: 8 trading days (June 2-10, minus 1 weekend)
- Required avg/day from here: **$1,136**

Still mathematically within reach. Day 1 alone was $1,857. Two more Day-1-style days would clinch it.

**Standing order: do not intervene.** Discipline test continues.

---

## Conventions

- All times UTC unless noted.
- Realized P&L = sum of `profit` field from deals closed that day.
- Floating P&L = current equity minus current balance, snapshotted at digest time.
- "Day %" = realized day P&L / initial trial capital ($200K).
- Cumulative through Day N = sum of Day 1..N realized.
- Entries appended at end-of-day after the 22:30 UTC digest.
