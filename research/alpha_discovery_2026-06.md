# Alpha Discovery — Phase 1 Conclusion (2026-06-20)

> After the roster was proven edgeless, built the alpha gatekeeper (walk-forward OOS +
> White's Reality Check) and tested the one within-reach hypothesis: regime-gating.

## The gatekeeper (durable win)

`backtest/alpha_search.py` judges any candidate on **out-of-sample** performance only and
corrects the **whole batch** for multiple testing via **White's Reality Check** (STW 1999).
This is the reusable instrument the project never had — every future strategy passes through
it before it's believed. Validated on the dead roster (LondonFix OOS P(edge>0)=0.1%; AUDJPY's
mild OOS Sharpe 0.70 correctly rejected by RC at p=0.79).

## Regime-gating experiment (the chosen hypothesis)

Hypothesis: trend-following works only in trending regimes; mean-reversion only in ranging
regimes. Built `strategies/regime_gated/` (Donchian-breakout-trend + z-score-fade-MR, each
gated by ADX, indicators self-tested). Ran 7 regime candidates + the roster baseline through
the gatekeeper.

| candidate | OOS days | Sharpe | OOS total% | P(edge>0) |
|---|---|---|---|---|
| RegimeTrend[adx] XAUUSD H1 | 747 | +0.34 | +7.4% | 72% |
| RegimeMeanRev[adx] EURUSD H1 | 147 | +0.84 | +2.7% | 74% |
| RegimeTrend[adx] AUDJPY H4 | 147 | +0.71 | +1.0% | 70% |
| (4 others) | — | negative | negative | <31% |

**White's Reality Check: best = RegimeTrend[adx] XAUUSD H1, multiplicity-corrected p = 0.576
→ NOTHING survives.** Regime-gating did not produce a strategy that clears honest correction.

## Honest read

- The **only thread** with both a real sample and consistent positivity is **gold
  trend-following in trending regimes** (XAUUSD H1, +7.4% over 747 OOS days). But Sharpe 0.34
  is not deployable, and it fails White's RC. It's a direction, not an edge.
- Everything else is noise or negative. The mildly-positive small-sample candidates (EURUSD MR,
  AUDJPY trend at ~147 days) are exactly what RC exists to reject — luckiest-of-many.

## Strategic conclusion

Single-symbol technical strategies on FX majors + gold show **no edge that survives honest
out-of-sample multiple-testing correction** — now confirmed four independent ways (trial,
full-sample, OOS, regime-gated). The deep lesson of White's RC: you cannot out-*search* your
way to edge by trying more single-symbol technical variants — each new try raises the bar.
Real edge requires a genuinely different **source**, not another indicator combination.

The higher-probability sources, per the StoneX/Nautilus research and the project priors, are
**structural and mostly M11/post-funded**:
- **Crypto with real L2 order-flow** (Hyperliquid) — genuine microstructure edge exists where
  the data is real and the horizon is short.
- **Cross-sectional / relative-value** (needs a multi-symbol engine; single-symbol engine
  can't express it) — e.g. the EURUSD/GBPUSD/EURGBP triangle, gold-vs-DXY.
- **Carry / risk-premia** (needs rate/swap data).

## Recommendation

Stop mining single-symbol FX technicals — the evidence is now strong enough that further
grinding is low-EV. Keep the gatekeeper as the permanent quality bar. The next genuine alpha
work is structural (multi-symbol engine + crypto L2), which lands naturally in the M11
Nautilus phase. Meanwhile the live trial keeps running frozen-C2 for free safety data; no
paid Challenge until something clears this gate.
