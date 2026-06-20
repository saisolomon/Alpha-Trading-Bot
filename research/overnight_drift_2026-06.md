# Overnight-Drift Hunt — Best FTMO-Shaped Lead Yet, but Financing-Gated (2026-06-20)

> Hunting the high-Sharpe intraday-profile edge prop firms reward. Tested the overnight-vs-
> intraday decomposition (Lou-Polk-Skouras) on 9 equity-index ETFs, 1993-2026
> (`backtest/overnight_drift.py`). The overnight premium is REAL and high-Sharpe gross; FTMO
> viability hinges on the index-CFD financing rate.

## Findings

**Gross (clean literature replication):** US indices accrue their return OVERNIGHT, not
intraday — SPY/QQQ/IWM/DIA overnight Sharpe 0.71-1.02, intraday Sharpe ~0 (QQQ +14%/yr
overnight vs +0.0% intraday). Non-US ETFs show the reverse (their "overnight" spans the
foreign session) → the clean signal is **US-only**.

**US-only long-overnight book, robust across ALL eras** (net @1bp/fill): pre-2013 Sharpe 0.72,
2013-2019 0.72, 2020+ 0.48 — durable, not era-dependent. Gross Sharpe 1.10.

**Fully loaded (spread + overnight CFD financing) — the decisive table:**

| financing %/yr | @0.5bp | @1.0bp | @1.5bp |
|---|---|---|---|
| 3% | **0.60 / +6.7%** | 0.38 / +4.2% | 0.15 / +1.7% |
| 5% | 0.42 / +4.7% | 0.20 / +2.2% | −0.03 |
| 7% | 0.24 / +2.7% | 0.02 | −0.21 |
*(net Sharpe / net ann.%)*

## Why this matters for the prop path

Overnight drift is **the best FTMO-shaped lead found so far** — and structurally far better
than momentum for a prop account:
- **Higher Sharpe** (0.6-0.9 net-of-spread vs momentum's 0.6).
- **Tight overnight drawdown** — overnight index moves are small/stable → fits FTMO's 10%
  floor far better than momentum's fat tails (momentum needed de-risking to ~2%/yr; this
  doesn't have the crash-tail problem).
- **Short hold, flat intraday, flat over weekends** (skip Fri→Mon) → FTMO-standard-compatible.

## The one gating unknown: CFD overnight financing

A long index CFD pays financing every night (~benchmark + markup − dividends). That cost is
*comparable to the premium itself*, so viability flips on it:
- **Low financing (~3%) + tight spread (~0.5bp): Sharpe 0.60, +6.7%/yr — deployable, FTMO-shaped.**
- **Typical retail (5-7%) + 1bp: Sharpe 0.02-0.20 — marginal to dead.**

Retail prop CFDs usually carry HIGH financing, so the realistic case is marginal — but it's
not settled until we have FTMO's actual numbers.

## Next steps (concrete)

1. **Pull FTMO/OANDA's published swap (financing) rates** for US500/US100/US30 long positions.
   This single number decides whether overnight drift clears the FTMO gate. (If FTMO's index
   swaps are low → real FTMO strategy; if typical → marginal.)
2. **Futures route:** on index FUTURES (MES/MNQ) there is NO separate overnight financing
   (it's in the basis) → the net-of-spread-only Sharpe (~0.65-0.87) applies → far more viable.
   That points to the **self-funded / MFF futures** path, not FTMO CFDs. (Note: mff-bot already
   killed *single-instrument* overnight on MES/MNQ; this is the broader multi-US-index version
   — worth a fresh look there.)
3. If FTMO financing kills it, the honest conclusion repeats: high-Sharpe edges that need
   overnight holds are penalized by retail CFD financing; the cleanest home is futures
   (self-funded/MFF) or a low-financing broker.

## RESOLVED 2026-06-20 — financing measured, overnight drift is DEAD on FTMO

Queried the live OANDA-Demo-1 terminal (`backtest/mt5_swaps.py`): **US100/US30/US500 long swap
= −6.15 to −6.16%/yr** (INTEREST_CURRENT mode — authoritative, the real server). Plugged in:

| spread/fill | net ann% | net Sharpe | yrs to +10% |
|---|---|---|---|
| 0.5bp | +3.6% | 0.32 | 2.7 |
| 1.0bp | +1.0% | 0.09 | 9.2 |
| 1.5bp | −1.5% | — | never |

At realistic index-CFD spreads, **net ~+1%/yr, Sharpe ~0.09 — not viable.** The 6.15% carry
eats the overnight premium, exactly as the financing-gated analysis predicted. Even the
optimistic 0.5bp case (Sharpe 0.32, ~3yr to pass) is below the high-Sharpe bar we needed.

**On FUTURES there is no separate overnight financing** (basis only) → the net-of-spread
Sharpe (~0.65–0.87) applies → viable. The edge is real; the FTMO-CFD venue's carry kills it.
Home = futures (MFF / self-funded), not FTMO CFDs.
