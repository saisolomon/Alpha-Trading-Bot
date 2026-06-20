# Walk-Forward Harness — First Real Results (2026-06-20)

> The payoff of the pivot. Three live roster EAs ported to Python (parity-verified), run
> through `backtest/engine.py` on the MT5 parity spine — the first backtest at n=hundreds
> of trades instead of the live handful. Engine: `backtest/run_roster.py`.

## Result — full cached history, net of modeled costs, $200k initial

| strategy | history | trades | win% | PF | ret% | maxDD% | Sharpe | **P(edge>0)** |
|---|---|---|---|---|---|---|---|---|
| LondonMomo (GBPUSD M15) | 2025-05→2026-06 (~13mo) | 178 | 47% | 0.87 | −8.1% | 18.6% | −0.81 | 17.0% |
| LondonFix (XAUUSD M15) | 2023-01→2026-06 (3.5yr) | 875 | 48% | 0.83 | −31.7% | 40.3% | −1.40 | **0.5%** |
| AudjpyTrend (AUDJPY H4) | 2025-05→2026-06 (~13mo) | 48 | 29% | 0.56 | −2.4% | 2.8% | −1.12 | 5.2% |

`P(edge>0)` = bootstrap probability (5,000 resamples, seed 42) that mean per-trade P&L is
positive — the project's anti-naive-Sharpe gate.

## Verdict: NO demonstrable edge in the current roster

- **All three are PF < 1.0 with negative Sharpe** net of costs, on real history.
- **LondonFix is a statistically significant LOSER** — P(edge>0) = 0.5% over **875 trades**.
  This is the clearest signal: the supposed "best carrier" does not survive its own history.
  (Plausible mechanism: it fades the pre-fix move, i.e. mean-reversion, while gold trended
  massively up 2023→2026 — a fade strategy bleeds in a trend. Consistent with the #46 finding
  that its "edge" is thin session-momentum, not real fix flow.)
- **AUDJPY trend-follow** loses too (P(edge>0)=5.2%, n=48): 29% win rate with only ~1.4:1
  payoff — trend-following needs bigger winners than it gets here.
- **LondonMomo** is the least-bad (P(edge>0)=17%) but still PF 0.87, negative — no edge, just
  a smaller sample that can't reject zero either way.

This **confirms with statistical weight** what the trial, the Tier-2 bootstrap, and the gate
review each suggested at smaller n: the roster has no proven edge. The harness did its job.

## What this means

- **Do NOT buy the paid Challenge with this roster.** Sizing was already over-hot (MC
  re-validation); now we know the edge itself is absent. Resizing makes it safe, not
  profitable; redeploying changes nothing.
- **The path to funded is NEW ALPHA, not redeployment.** The roster strategies need to be
  replaced/redesigned, then validated through THIS harness before any Challenge fee. This is
  the Alpha Factory's real job, brought forward.

## Honest caveats (bounding the claim)

1. **Raw-signal backtest** — the news-blackout, per-trade/cluster risk caps, and FTMO
   pretrade gates are execution-layer and intentionally omitted from the strategy ports. They
   would SKIP some trades, not reverse the sign — negative edge doesn't become positive by
   trading less.
2. **Full-sample, not yet walk-forward-split.** Full-sample negative edge is *more* damning
   than OOS-negative (no in-sample fitting could have rescued it). The formal IS/OOS +
   SPA/White layer (`walk_forward.py` + `tier2_bootstrap.py`) is the confirming next step but
   cannot turn a PF-0.83/875-trade loser into a winner.
3. **LondonMomo one-bar gate divergence** (parity verify, minor): a known timing shift; would
   not plausibly flip PF 0.87 / 17% to a real edge.
4. **AUDJPY engine fix validated here:** the trailing-stop port stacked positions until the
   engine gained a modify-in-place path (this commit); all 48 trades now exit as a single
   ratcheting stop — the result is mechanically sound, just unprofitable.
5. Bootstrap is per-trade-iid and per-strategy (no cross-strategy multiplicity correction);
   each strategy is assessed on its own merits.

## Next

- Formal walk-forward IS/OOS + SPA/White layer to stamp the kill verdicts rigorously.
- Then: stop iterating the dead roster; point the research at finding strategies that DO
  survive this harness. That — not a Challenge purchase — is the path to funded.
