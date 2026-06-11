# Tier-2 bootstrap: 10-EA universe, 10 trading days, B=10,000, seed 42

## Family-wise tests (the ones that count)

- White's Reality Check (max mean daily R): best rule = **EURUSD_M15_LondonMomo** (mean +0.510 R/day) -> **p = 0.252**
- Studentized max-t (SPA-flavoured): best rule = **EURUSD_M15_LondonMomo** (t = 1.00) -> **p = 0.638**

## Per-EA detail (uncorrected -- calibration only, NOT selection)

| EA | n trades | mean R/trade | daily mean R | daily t | boot p (day) | boot p (trade) |
|---|---|---|---|---|---|---|
| EURUSD_M15_LondonMomo | 11 | +0.46 | +0.510 | +1.00 | 0.147 | 0.156 |
| EURUSD_M15_RSIFade | 0 | — | +0.000 | +0.00 | — | — |
| US500_M15_ORB | 5 | -0.17 | -0.086 | -0.21 | 0.590 | 0.668 |
| XAUUSD_M15_LondonFix | 10 | +0.24 | +0.239 | +0.83 | 0.193 | 0.197 |
| BTCUSD_M15_TrendFollow | 0 | — | +0.000 | +0.00 | — | — |
| GBPUSD_H1_SwingBreak | 8 | -0.49 | -0.394 | -2.15 | 0.992 | 0.999 |
| XAUUSD_H1_NewsReaction | 0 | — | +0.000 | +0.00 | — | — |
| AUDJPY_H4_TrendFollow | 3 | -0.77 | -0.232 | -1.49 | 0.933 | — |
| EURGBP_H4_MeanReversion | 0 | — | +0.000 | +0.00 | — | — |
| US100_H1_OvernightDrift | 4 | -0.00 | -0.001 | -0.02 | 0.492 | — |

## Reading

- The family-wise null is "no EA in the 10-rule universe has positive
  expected daily P&L." With n=10 days, the corrected tests above show
  whether ANY rule's observed performance survives selection bias.
- Per-EA uncorrected p-values are reported only to calibrate magnitudes;
  picking rules off them would be exactly the data-snooping the RC exists
  to prevent.
- Trade-level bootstraps double-check the two carriers at their natural
  unit (n=11 / n=10 trades).

