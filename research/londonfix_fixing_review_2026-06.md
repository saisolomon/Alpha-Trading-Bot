# LondonFix vs the FX-Fixing Literature — Mechanism Review (Task #46)

> Deliverable for Tasks.md #46 (due ~6/19, gate packet). Re-reads the FX-fixing-scandal
> literature (Chaboud 2023 / `microstructure_execution_review_2026-06.md` C5, rec #2)
> against XAUUSD_M15_LondonFix, with a live-fire cross-check. Produced by the gate-review
> workflow 2026-06-20.

## Classification: (c) — ordinary early-London session momentum mislabeled as "fix flow"

The FX-fixing pathology does **NOT** transfer to this EA. **Keep at 0.50%, do NOT add a fix-window guard.** Rename-worthy but otherwise fine; the correct risk control is the USD-cluster cap already specced (Task #39, Baltas ERC), not a fix guard.

## Why the pathology fails to transfer — three independent grounds

The load-bearing fact is **timing**. The EA hardcodes "fix" = 10:30 but runs all session logic on `TimeCurrent()` (broker = OANDA UTC+3 summer DST), so it actually fires its fade at **~07:30 UTC**:

1. **Wrong instrument.** Chaboud 2023's fixing-scandal literature is **WM/R FX-fix-centric**. Gold price discovery is the **LBMA Gold Price electronic auction** (IOSCO-compliant since 2015) — a different mechanism with different participants.
2. **Wrong clock.** The EA trades neither the FX fix nor even the gold auction: it fires ~2h **before** the real LBMA AM auction (10:30 London = 09:30 UTC BST) and ~7.5h before the WM/R 4pm London FX fix (15:00 UTC). It trades the **pre-auction early-London momentum window and fades it.**
3. **Pre-reform irrelevance.** The WM/R 5-minute-window reforms regulated away exactly the front-running flow the literature documents — and none of it touches a 07:30-UTC gold trade.

## Live-fire cross-check

- **Gate week (6/11–6/19) gold record: ~3W / 4L** — wins +993, +1072, +961; losses −985, −1045, −973.
- **May trial: 6–4, PF 1.78.**
- **Loss mechanism is cross-asset USD beta, NOT fix-window adverse selection:** 98% of LondonFix's trial losses fell on USD-strength cluster days; DXY β ≈ −$1,088 per +1% move (R²=0.41); non-cluster record 6–1 (`trial_2026-05_postmortem.md` L78). The edge erodes on dollar-rip days, which a USD-cluster/DXY gate addresses — a fix-window guard would protect a window the EA does not trade.

## Verdict for the gate packet

- **Keep LondonFix at 0.50%.** It was the week's best carrier (~+$1,981 gold).
- **No fix-window guard.** Wrong instrument for the protection.
- **The real control is the USD-cluster cap** (already specced).
- **Honest caveat:** "session momentum, fade" is a thin, chart-and-clock-specific technical edge that did NOT survive the Tier-2 White Reality Check. 0.50% is a risk-bounded license, not proven alpha — **no upsizing.**

## Follow-on (separate from this review)

The dual-clock coherence bug surfaced here (window logic on broker `TimeCurrent()`, blackout gate on `TimeGMT()`) is tracked as the session-clock decision (Tasks.md #50). It does not change this classification but should be resolved so the EA's documented hours stop lying about the timezone.
