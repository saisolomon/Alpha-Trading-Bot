# Momentum → FTMO Deployment: Real Edge, Wrong Venue (2026-06-20)

> Sized the validated TS-12m edge for an actual FTMO account and simulated the daily bright
> lines (`backtest/momentum_ftmo.py`). Conclusion: **the edge can be made FTMO-legal, but
> only by de-risking so hard the return goes glacial — FTMO's tight static floor is
> fundamentally mismatched to a monthly momentum strategy.** The edge's real home is
> self-funded capital (M11/IBKR), not an FTMO Challenge.

## The numbers

Raw vol-targeted (FTMO-mappable universe, $100k, 20bps), daily-path FTMO-rule sim:

| vol target | ann.ret | maxDD | min equity vs init | FTMO daily (5%) | FTMO max (10%) |
|---|---|---|---|---|---|
| 4% | +2.6% | −11.9% | −9.9% | ok | ok (barely) |
| 5% | +3.2% | −14.8% | −12.2% | **BREACH** | **BREACH** |
| 6%+ | higher | worse | worse | BREACH | BREACH |

Even at 4% vol the raw strategy draws ~12% and grazes the 10% floor — momentum's fat left
tail ("momentum crashes": sharp synchronized trend reversals) isn't tamed by vol-targeting.

**With de-lever-only CPPI drawdown control + crypto removed** (crypto's daily gaps threaten
the 5% daily line):

| base vol | ann.ret | min equity vs init | FTMO daily | FTMO max | internal 3%/7% |
|---|---|---|---|---|---|
| **4%** | **+1.5%** | −2.2% | ok | ok | **CLEAR** |
| 5% | +2.0% | −2.7% | ok | ok | daily touch |
| 6% | +2.5% | −3.1% | ok | ok | daily touch |
| 8% | +3.7% | −3.5% | BREACH | ok | daily |

CPPI works (min-equity-vs-initial held to ~−3%, FTMO max never breached). **The largest fully-
clean sizing is ~4–6% vol → +1.5–2.5%/yr.**

## The verdict: structural venue mismatch

At an FTMO-legal sizing, momentum returns **~+2%/yr → ~3–4 YEARS to pass Phase 1's +10%.**
That's not a viable funding path. And it's not a tuning problem — it's structural:

- FTMO's **static 10% max-loss floor + 5% daily** rewards **high-Sharpe, short-holding,
  tight-stop intraday** strategies.
- Monthly cross-asset momentum is **Sharpe ~0.6 with fat-tailed, multi-month drawdowns**
  (Calmar ~0.3–0.5: DD ≈ 2× annual return). To target +10% you must risk >10% DD; to cap DD
  <10% you must shrink return to ~2%/yr. You cannot have both under this floor. It's a Calmar
  argument, robust to the sim's caveats (close-to-close daily proxy, ETF proxies, simple CPPI).

## Where this edge actually belongs

1. **Self-funded (M11 / IBKR)** — the right home. No artificial drawdown floor → run at full
   ~10% vol for **+6–7%/yr, compounding**, which is exactly how TSMOM is deployed in practice
   and in the literature. This is a real, ownable strategy for real capital.
2. **A prop firm with a trailing / looser drawdown** suited to swing strategies (most, incl.
   FTMO, have tight static floors — would need to shop venues).
3. **NOT a standard FTMO Challenge.**

## Honest takeaways

- **We found a real, robust, statistically-validated edge** — the first in the project. That
  stands. It's genuinely valuable for self-funded capital.
- **FTMO is the wrong vehicle for it.** The disciplined apparatus just saved us from deploying
  momentum on FTMO and either bleeding via over-sizing or never passing via under-sizing —
  discovered before spending a dollar.
- **The FTMO funding question is now sharply framed:** FTMO wants a *high-Sharpe intraday*
  edge, which our research shows is hard in single-symbol FX. The realistic paths are (a) keep
  hunting specifically for an FTMO-shaped (high-Sharpe, tight-DD) edge, or (b) redirect the
  validated momentum edge to self-funded deployment where it actually fits.

## Next-step options (user's call)

- **Pivot momentum to the self-funded M11 track** (Nautilus + IBKR) — deploy the edge where it
  fits, on own capital.
- **Keep hunting for an FTMO-shaped edge** — high-Sharpe intraday; harder, lower-prior.
- **Shop prop firms** whose drawdown structure suits swing/momentum.
