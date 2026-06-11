# Tier-2 Bootstrap Reality Check — Verdict (M10 Tier-2, bootstrap portion)

> Produced 2026-06-11. Script: [`tier2_bootstrap.py`](tier2_bootstrap.py) (seed 42, B=10,000),
> raw output: [`tier2_bootstrap_output.md`](tier2_bootstrap_output.md), dataset: the committed
> trial deals export. Implements the MANDATORY data-snooping gate from Tasks.md
> (Sullivan-Timmermann-White 1999 / Park-Irwin 2007 / Neely 2011): White's Reality Check +
> a studentized max-t (SPA-flavoured) variant over the FULL 10-EA selection universe,
> with joint day-resampling that preserves the cluster correlation exactly.
> Walk-forward + purged CV (the rest of the Tier-2 task) await the backtest harness +
> a longer OANDA cache — this document covers the bootstrap gate only.

## Results

| Test | Best rule | Statistic | p (corrected) |
|---|---|---|---|
| White's Reality Check (max mean daily R) | EURUSD_M15_LondonMomo | +0.510 R/day | **0.252** |
| Studentized max-t | EURUSD_M15_LondonMomo | t = 1.00 | **0.638** |

**No EA in the 10-rule universe survives multiple-testing correction at 5%.** A best-of-ten
looking as good as LondonMomo did arises ~25% of the time under the no-edge null in two weeks
of data. Uncorrected per-EA p-values (calibration only): LondonMomo 0.147 day / 0.156 trade;
LondonFix 0.193 / 0.197; **GBPUSD_H1_SwingBreak 0.992 / 0.999** — i.e., its NEGATIVE
performance is about as close to significant as anything gets at this n.

## Verdict — what this licenses and what it forbids

1. **Nothing is "proven."** Two weeks cannot statistically validate an edge against a 10-rule
   selection universe, and this run says so with numbers instead of vibes. This was the expected
   outcome, stated in advance in the sizing calibration ("provisional pending Tier-2").
2. **Config C2 retains its license — as a risk-bounded exploration bet, not a proven edge.**
   C2 never claimed significance: its sizes came from Bayesian cold-start shrinkage and
   P(ruin) gates that bound the account's downside REGARDLESS of whether the edge is real
   (10,000-path worst case ≈ -$2.2K, no path near any FTMO line). The bootstrap changes
   nothing about that logic. The paid Challenge proceeds at C2 with this framing explicit.
3. **What the bootstrap FORBIDS: upsizing on this sample.** Config C3 (Momo at 0.75%) and any
   "the carriers are proven, lever up" reasoning are blocked until a materially longer sample
   (dry-run week + Challenge data + walk-forward on extended OANDA cache) clears a corrected
   test. This is the entire point of the gate — it prevents confident scaling of noise.
4. **The kill side is the statistically strong result.** SwingBreak's uncorrected p ≈ 0.99+
   (wrong tail) means its kill stands on evidence, not taste. AUDJPY (0.933) earns its
   hold-at-minimum. The asymmetry is typical: two weeks can nearly prove a strategy is BAD;
   it cannot prove one is good.
5. **Roster actions re-confirmed, none changed:** C2 three-EA roster, sizes, caps — all stand.
   The benched EAs' paths (dry-run-week evidence, news-clock fix validation, cointegration
   gate) are unaffected.

## Standing instruction inherited by future selection rounds

Any future addition/upsizing decision computes its corrected p against the FULL universe of
rules ever tried (the research ledger in M11 exists precisely to keep that universe honest).
Uncorrected per-EA p-values are calibration output, never selection input.
