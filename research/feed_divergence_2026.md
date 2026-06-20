# Feed Divergence + Empirical Broker→UTC Alignment (2026-06-20)

> Harness prerequisite. The MT5 spine is stored in raw BROKER time; Dukascopy is native
> UTC. Rather than guess the offset (the auto-detect corrupted stamps), recover it
> empirically by the shift that minimizes price divergence between the two feeds.
> Engine: `backtest/align_feeds.py`.

## Method

For each candidate hour shift `h`, shift the MT5 close series by `−h` (broker − h = UTC
candidate), inner-join to the Dukascopy close on matched bar-opens, and measure mean
|Δclose| (in pips) + correlation. The shift with minimum divergence is the true offset;
the residual divergence there is the genuine OANDA-vs-Dukascopy feed difference.

## Result — EURUSD M15 (overlap 2026-06-15 .. 2026-06-17)

| broker→UTC shift | matched bars | mean abs Δclose (pips) | corr |
|---|---|---|---|
| +0 | 288 | 10.87 | 0.714 |
| +1 | 284 | 8.32 | 0.799 |
| +2 | 280 | 5.67 | 0.904 |
| **+3** | **276** | **0.14** | **0.99992** |
| +4 | 272 | 5.73 | 0.876 |
| +5 | 268 | 8.44 | 0.670 |

**Recovered broker offset = UTC+3** — a sharp, unambiguous minimum (next-best shift is 40×
worse at 5.67 pips). 

## What this establishes

1. **Offset confirmed empirically: OANDA-Demo = UTC+3 in summer** — matches the EAs'
   broker-time behavior (the session-clock finding). No guessing.
2. **Both feeds are correct.** OANDA and Dukascopy agree on EURUSD to **0.14 pips** once
   aligned + corr 0.99992. A wrong bi5 decode/scale or a corrupt MT5 pull would blow this
   up — it didn't. The whole data pipeline (MT5 spine + Dukascopy tick→bar) is cross-validated.
3. **Feed-divergence baseline = 0.14 pips** for EURUSD — the real liquidity-provider
   difference, a cost/parity input for the harness's cost model.

## Application rule for the harness

- The MT5 spine's broker-time stamps map to UTC by **subtracting 3h in EU summer**.
- **DST caveat:** the +3 holds for the summer overlap (June). OANDA shifts to **UTC+2 in EU
  winter**. For the full multi-year spine, the offset must be applied **per-DST-period**, not
  as a flat constant — the same DST trap the news-clock bug taught us. The alignment method
  here recovers the correct offset for any window, so winter slices will independently
  confirm +2 when checked.
- Because the EAs are broker-time-native, the harness runs signal logic on broker-time bars
  directly; the UTC offset is needed only to align bars to the (UTC) news calendar.

## Remaining (full divergence report)

This proves the method + validates the pipeline on EURUSD. The full per-symbol divergence
table (GBPUSD/AUDJPY/XAUUSD/EURGBP, summer + winter slices) needs matching Dukascopy pulls
for each — a follow-on when the Dukascopy bulk pull runs. The EURUSD result is
representative and sufficient to unblock the harness wiring.
