# C2 Sizing-MC Re-Validation — Result (2026-06-20)

> GO-condition #1 from the gate review. Engine: `mc_revalidation_2026-06.py` (same bootstrap
> + seed 42 as the original `trial_sizing_calibration.py`). Inputs: May raw deals +
> `trial_2026-06_live_deals.json` (the live-fire week). **Verdict: GO-condition #1 FAILS.**

## What was tested

The original C2 sizing MC (Momo 0.50% / Fix 0.50% / AUDJPY 0.25%) pre-registered a 10-day window
p5 of −$2,244 and "worst of 10K paths never approached the daily line." The live week realized
**−$5,090**. Two tests:

## TEST A — falsification (live week vs the original May-only model)

Bootstrapping the May-only C2 daily pool at the live week's horizon, the realized **−$5,090 lands
at the 1.84th percentile** — a genuine left-tail event the original model materially under-weighted.
Falsification **confirmed**: the model's tail was too thin.

## TEST B — re-estimation (pool the live week into the bootstrap, 10-day horizon)

| Distribution | P(touch 5% daily) | **P(touch 10% max)** | 10-day p5 | 10-day median |
|---|---|---|---|---|
| C2 May-only (original) | 0.00% | **0.04%** ✓ | −$2,793 | +$6,089 |
| **C2 May+live pooled** | 0.00% | **1.37%** ✗ | **−$8,899** | **+$605** |

Pooling one week like the one we just saw, **C2 at full size breaches the max-loss gate by 13.7×**
(1.37% vs the 0.1% limit), the p5 worsens 3.2× (−$2.8k → −$8.9k), and the median edge collapses
from +$6,089 to ~+$605 (≈ zero).

## Re-solve — what size passes the gates on the pooled distribution?

| k × C2 | eff. Momo/Fix/AUDJPY | P(touch 10% max) | gate |
|---|---|---|---|
| 1.00× | 0.50 / 0.50 / 0.25% | 1.37% | ✗ |
| 0.75× | 0.38 / 0.38 / 0.19% | 0.13% | ✗ |
| **0.60×** | **0.30 / 0.30 / 0.15%** | **0.00%** | ✓ |
| 0.50× | 0.25 / 0.25 / 0.12% | 0.00% | ✓ |

**Smallest size passing both gates: 0.60× C2 ≈ Momo 0.30% / Fix 0.30% / AUDJPY 0.15%.**

## Verdict & honest caveats

- **GO-condition #1 FAILS at the deployed C2 size.** C2 (0.50/0.50/0.25%) is too hot given the
  now-observed loss distribution; it must come down to ≤ 0.60× before any paid Challenge.
- **De-risking makes it SAFE, not PROFITABLE.** The pooled median edge is ~0 at *any* size; cutting
  size shrinks an already-near-zero edge in absolute terms. The binding problem is **no demonstrated
  edge**, which sizing cannot fix — so the **walk-forward harness (find real edge), not a resize, is
  the priority.** A resize only earns the right to attempt; it does not create the reason to.
- **Statistical caveat:** the pooled pool is 16 daily vectors, 6 of them one non-IID bad week (May
  ran the over-risked Config A roster; the week ran C2). Treat magnitudes as **directional**. The
  direction — C2 too hot at the observed tail, edge ≈ 0 — is robust; the exact safe-k needs the
  harness's larger sample to pin down.

## Bottom line for the Challenge decision

The re-validation does NOT clear the no-go — it sharpens it. Even setting edge aside, the deployed
sizing fails its own safety gate once the live tail is included. The path forward is unchanged and
reinforced: **build the harness, find whether real edge exists, and only then re-derive sizing** —
rather than buying a Challenge on a book that is both unproven *and* (at current size) over-risked.
