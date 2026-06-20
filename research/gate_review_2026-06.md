# Gate Review — Live-Fire Trial Week (2026-06-20)

> Formal gate review after the 7-trading-day live-fire week (6/11–6/19) on the fresh
> FTMO-via-OANDA free-trial account (1600146279, $200k). 5-lens + adversarial workflow.
> **Decision: NO-GO on the paid Challenge. Pivot to the walk-forward harness.**

## Verdict (split)

- **SYSTEM / infrastructure: PASS.** The machine lost a genuinely adverse week (one green day, then a 5-day bleed; 4W/8L = 33%; −$7,127 off the Friday peak) while staying fully legal — $14,910 (~7.5%) headroom to the FTMO max-loss floor, **zero kills, zero FTMOImminent, watchdog armed throughout, telemetry never dropped.** §3 invariants are real in code (EquityWatchdog 1s independent OnTimer + Prague-DST roll; three breakers; 250 ms equity poll; libquant parity-tested gate) and were converted from "armed" to "proven" by the passed kill/outbox drills + 88 s reboot recovery. Losing money **safely and legally** is the pass condition for a live-fire trial; the system did exactly that.
- **STRATEGY / edge: FAIL.** Combined live record (May 41 + week 12 = 53 trades): **21W/32L (39.6%), net −$4,926 (−2.46%).** Beta(22,33) posterior P(true win-prob > 0.5) ≈ 0.06 — the live data now mildly favors a *sub-breakeven* win rate. Nothing survived White's Reality Check (best corrected p=0.252). C2 remains a risk-bounded license, never proven alpha; **upsizing forbidden.**

## The decisive finding (the adversary caught it; all 5 lenses + the operator missed it)

The C2 sizing Monte Carlo (`trial_2026-05_sizing_calibration.md` line 46, seed-fixed 10,000 paths) **pre-registered p5 = −$2,244 / median +$6,723 per 10-day window**, asserting "the worst of 10K paths never approached the daily line." The live week realized **−$5,090 — ~2.3× worse than the model's own 5th percentile**, landing around the ~1st-percentile tail or beyond.

This is **out-of-sample falsification of the sizing model's tail.** It is stronger and more deploy-blocking than the edge p-values: the entire pro-Challenge case ("survival is the real pass condition, and p5 is only −$2,244, so the downside is bounded") rests on the very object the live draw just broke. For a −5%/−10% instant-fail product, a no-time-limit grind is only an asset if the per-window loss distribution is trustworthy — and it is now demonstrably not.

## Per-item verdicts

| Item | Verdict |
|---|---|
| **news-clock** (NewsBlackout.mqh) | **Code-correct but UNEXERCISED.** Calendar `D'2026.06.18 11:00'` + ±5 min window correct; all gate sites pass TimeGMT(). But the block path fired **0 times** (FOMC outside session hours; BoE LondonFix entered 10:30/exited 10:36, legitimately outside 10:55–11:05). Structural flaw: a ±5 min entry-only gate can essentially never fire for LondonFix, which opens ~30 min ahead of an 11:00 BoE and holds through it. Not validated. |
| **RSIFade** | **KILL.** Failed its rejoin gate ("fire with sane frequency") — 0 of 490 signal events all week, consistent with 1 signal in 14 days in the replay. A non-firing EA has no testable edge, can't be validated by waiting, and is pure operational drag. Revival is free if re-specced. |
| **NewsReaction** | **KEEP BENCHED-OBSERVING.** Met its gate (evaluated the correct post-BoE 12:00 bar vs the trial's 3h-early bug); the low-vol skip was the filter working, not a malfunction. But one non-firing event is proof-of-mechanism, not edge — no live slot. |
| **LondonFix** (Task #46) | **Classification (c): early-London session momentum mislabeled as "fix flow."** FX-fixing pathology does NOT transfer (wrong instrument, wrong clock, pre-reform-irrelevant). Keep 0.50%, **no fix-window guard** (it would protect a window the EA doesn't trade); correct control is the USD-cluster cap. See `londonfix_fixing_review_2026-06.md`. |
| **session-clock** | PASS for safety (Prague-DST roll correct). Residual coherence risk: LondonFix runs window logic on broker TimeCurrent() but the gate on TimeGMT() — two clocks; root of the (c) misclassification. Track, not blocking. |

## The GO conditions (re-offer the paid Challenge when ALL three clear)

NO-GO is **conditional and cheap to revisit** — days of harness work, not months:

1. **Model re-validation** — append the live week to the C2 sizing MC, re-estimate the loss distribution, confirm realized P&L sits inside a re-estimated p5. (Directly answers the tail falsification.) **→ RESOLVED 2026-06-20: FAILS.** `mc_revalidation_2026-06.md`: live week = 1.84th pctile of the May-only distribution; pooling it in, C2 full-size breaches the max-loss gate 13.7× (P(max touch) 1.37% vs 0.1%); p5 −$2.8k→−$8.9k; median edge +$6,089→~+$605. Safe only at ≤0.60× C2, but edge ≈0 at any size. So sizing must come down **and** real edge must be found — reinforces the harness pivot.
2. **Cluster-gate confirmation** — produce ONE live-or-replay observation that the 0.75% USD-counter sub-cap actually *fired* on a USD-cluster day. (This week's losses are the same cluster legs May diagnosed, but no one confirmed the fix triggered, or that a cluster day even occurred.)
3. **Roster parity** — verify the deployed live manifest == corrected-C2 (SwingBreak/ORB/Drift cut, EURUSD-Momo EURUSD-chart detached, sub-cap wired). Every lens inherited the C2 framing without re-checking it against the live manifest.

## Open caveats (recorded, not yet resolved)

- **Non-IID pooling:** the 53-trade read pools May (over-risked Config A, which failed its own max gate) with the week (C2). Two risk configs ≠ one distribution. The negative *direction* survives (asymmetry: two weeks can nearly prove BAD, never GOOD; live drift is toward the provable-bad tail), but magnitudes are softer than a single-distribution read implies.
- **Power:** n=53 can never *prove* a Sharpe≈1 edge (~600+ trades needed). Absence of edge-significance was inevitable; the informative signals are the ones in the provable direction (SwingBreak wrong-tail p≈0.99; this week's MC-tail breach).
- **Option economics:** the free-retry framing prices only the ~$1,080 fee, ignoring that a failed attempt burns calendar against an unproven book, adds another multiplicity peek (widening the null band), and risks commitment escalation. The harness pivot generates the one missing thing — out-of-sample length — at near-zero marginal cost.

## Next action

Pivot to the walk-forward harness (`backtest/fetch_history.py` → `backtest/walk_forward.py`), kill RSIFade, keep NewsReaction benched. The harness is the only mechanism that produces the out-of-sample length both the edge question and the now-impugned tail-model question require. The live trial account keeps running frozen-C2 (it's free and the safety data is still useful); no money goes to a paid Challenge until the three GO conditions clear.
