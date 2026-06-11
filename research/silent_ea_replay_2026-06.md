# Silent-EA Log Replay — RSIFade + NewsReaction (M10 diagnosis)

> Produced 2026-06-11 from the on-disk MT5 Experts logs (MQL5/Logs, 2026-05-28 → 06-10).
> Log timestamps verified as LOCAL EDT (UTC-4) by cross-matching the 6/10 GBPUSD zombie
> fill (log 19:56:11 = Convex dealTime 23:56 UTC). Both "silent" EAs turned out to be
> ALIVE — and their silences had two different root causes, one of which affected the
> ENTIRE portfolio, not just the silent EAs.

---

## 1. EURUSD_M15_RSIFade (on USDJPY chart) — dry-run flip miss

**Evidence:** exactly one signal line in 14 days:
```
20260602.log 10:30:01 EDT (14:30 UTC)
[EURUSD_M15_RSIFade:USDJPY.sim] DRY-RUN: would SELL 28.55  rsi=81.4  sl=159.89529 tp=159.83871
```

**Diagnosis:** the EA's logic is alive — RSI(14) crossed its 80 overbought threshold and produced
a fully-formed signal. **It was never flipped out of dry-run** during the 5/27 go-live (the same
config miss as BTCUSD_M15_TrendFollow — this is the SECOND occurrence of the bug class).
Secondary observation: one signal in 10 trading days is genuinely low frequency for an RSI-fade
(strict 80/20 thresholds on M15), so even live it would have contributed ~1 trade.

**Verdict: stay BENCHED, two conditions to rejoin:** (1) the pre-Challenge 7-day dry-run week
must show its signals firing with sane frequency (it costs nothing — dry-run is its current
state); (2) any rejoin enters at 0.25% with the standard gates. Note it trades USDJPY — NOT in
the USD-counter cluster set — so it would add genuine diversification if it earns its slot.
**Outcome of the would-be 6/02 trade is unknowable** without USDJPY M15 data (MT5 stood down);
not estimated, per no-invented-numbers.

## 2. XAUUSD_H1_NewsReaction — the news-clock bug (SYSTEMIC)

**Evidence:** three skip lines, all of the form `news bar range X < 0.8*ATR Y; skip`:

| Log date | Log time (EDT) | = UTC | Matched event (actual release) |
|---|---|---|---|
| 6/04 | 06:00 | 10:00 | ECB decision (12:45 CEST presser ≈ 12:45 UTC entry in table) |
| 6/05 | 07:00 | 11:00 | **NFP** (actual release 12:30 UTC) |
| 6/10 | 07:00 | 11:00 | **US CPI** (actual release 12:30 UTC) |

**The EA matched all the right events — and evaluated every one of them ~90 minutes BEFORE the
actual release,** measuring quiet pre-news bars that correctly failed its 0.8×ATR big-bar filter.

**Root cause #1 — clock mismatch:** `kNewsCalendar2026[]` stores UTC datetimes, but every EA
passed `TimeCurrent()` — **broker time, UTC+3 on OANDA**. The arithmetic closes exactly:
NFP entry `13:30` read against a UTC+3 clock ⇒ matched from 10:30 UTC; the H1 bar-close
evaluation at 11:00 UTC sits at the 90-min lookback edge ⇒ the observed 07:00-EDT skip.
The doc comment in NewsBlackout.mqh literally taught the bug:
`if (IsNewsBlackout(TimeCurrent())) return;` was the written usage example.

**Root cause #2 — DST hardcoding:** the calendar pinned US events at winter UTC offsets
year-round (NFP/CPI `13:30`, FOMC `19:00`). Summer releases are 12:30/18:00 UTC. ECB and BoE
rows had the equivalent CET/UK errors. So even with the right clock, summer events were +1h off.

**Systemic impact — this affected EVERY EA, not just NewsReaction:** `IsNewsBlackout` windows
were shifted ~3h early for the whole trial. The protective blackout the other nine EAs relied on
**did not cover the actual release minutes** of ECB 6/04, NFP 6/05, or CPI 6/10. (Notably, CPI
6/10 12:30 UTC landed on the worst day of the trial; the gold-fix EA stopped out at 11:00 UTC
that day before the release — the blackout never stood between any EA and the real event.)
The trial's risk caps did the protecting; the news system was decorative.

**Fixes APPLIED (this commit), all 11 programs recompiled 0-errors:**
1. Calendar rewritten with DST-correct UTC times (27 rows), each annotated EST/EDT/CET/CEST/GMT/BST,
   with 2026 DST boundaries documented (US Mar 8–Nov 1; EU/UK Mar 29–Oct 25).
2. **Clock contract** documented loudly in NewsBlackout.mqh: callers MUST pass `TimeGMT()`.
3. All 9 EAs' call sites swept: `IsNewsBlackout/MinutesToNextNews/RecentNewsEvent` now receive
   `TimeGMT()` (retired/benched EAs included — no relapse on revival).

**Verdict: stay BENCHED, strong rejoin candidate.** The strategy's thesis was never actually
tested — it spent the trial reading the wrong clock. With the fix, the pre-Challenge dry-run week
contains FOMC 6/17 18:00 UTC and BoE 6/18 11:00 UTC as live test events: if it now evaluates the
TRUE post-release bar (and trades or skips on real bar size), it has demonstrated the fix and can
be considered for the roster at 0.25% — subject to the USD-cluster cap (XAUUSD is in the cluster).

## 3. EURGBP_H4_MeanReversion (for completeness)

Zero log lines beyond inits — zero 3σ z-score deviations in 10 days, statistically unremarkable
for the pair. No bug found, nothing to fix. Stays benched behind the cointegration-stability gate
(M10 cost-model task), unchanged.

## 4. Scoreboard updates this forces

- **Dry-run flip misses are now a CLASS (BTC, RSIFade).** The pre-Challenge runbook gets a hard
  checklist line: enumerate every attached chart's `InpDryRun` via the heartbeat's eaStates
  (dryRun flag is already collected!) and refuse go-live while any roster EA reports dry-run.
  The monitor surfaces this for free — we just never alerted on it.
- **The post-mortem's implicit "news blackout worked" assumption is retracted** — the blackout
  never aligned with a real event during the trial. P&L facts are unchanged; the protection
  narrative is corrected here.
- The 2026 calendar is now DST-correct, but it remains hardcoded — the M10 Tier-2
  "NewsBlackout API-based optional path" task (MT5 Calendar API with hardcoded fallback) is the
  durable fix and inherits the TimeGMT contract.
