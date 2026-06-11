## 1. Per-EA R-multiple stats + Bayesian binary Kelly

(R = trade P&L / $500 risk unit. Prior on win prob: Beta(2,2). f*bin = p − (1−p)/b. Conservative = posterior 25th pct of p.)

| EA | n | mean R | std R | win p̂ (post.) | p 25th | b (W/L) | f*bin(mean p) | f*bin(p25) | ½·f*bin(p25) |
|---|---|---|---|---|---|---|---|---|---|
| EURUSD_M15_LondonMomo | 11 | +0.46 | 1.52 | 0.60 | 0.52 | 1.08 | +0.231 | +0.070 | 0.035 |
| US500_M15_ORB | 5 | -0.17 | 1.97 | 0.44 | 0.33 | 1.23 | -0.006 | -0.215 | 0.000 |
| XAUUSD_M15_LondonFix | 10 | +0.24 | 0.91 | 0.57 | 0.48 | 1.19 | +0.211 | +0.049 | 0.024 |
| GBPUSD_H1_SwingBreak | 8 | -0.49 | 0.62 | 0.25 | 0.16 | 1.17 | -0.389 | -0.557 | 0.000 |
| AUDJPY_H4_TrendFollow | 3 | -0.77 | 0.41 | 0.29 | 0.16 | nan | +nan | +nan | nan |
| US100_H1_OvernightDrift | 4 | -0.00 | 0.25 | 0.38 | 0.25 | 2.91 | +0.160 | -0.003 | 0.000 |

## 2. Classical continuous Kelly + G(f) curves (per spec)

f* = μ_R/σ_R² (fraction of equity risked per TRADE). G(f) = f·μ − f²σ²/2 per trade, in equity-log units.

| EA | f* (cont.) | G(f=0.10%) | G(f=0.25%) | G(f=0.50%) | G(f=0.75%) | G(f=1.00%) | G(f=1.25%) |
|---|---|---|---|---|---|---|---|
| EURUSD_M15_LondonMomo | +20.05% | +4.62 | +11.51 | +22.88 | +34.10 | +45.18 | +56.11 |
| US500_M15_ORB | -4.43% | -1.73 | -4.41 | -9.06 | -13.95 | -19.09 | -24.46 |
| XAUUSD_M15_LondonFix | +28.72% | +2.38 | +5.94 | +11.83 | +17.67 | +23.46 | +29.19 |
| GBPUSD_H1_SwingBreak | -130.23% | -4.93 | -12.34 | -24.70 | -37.08 | -49.49 | -61.92 |
| AUDJPY_H4_TrendFollow | -451.16% | -7.75 | -19.37 | -38.76 | -58.16 | -77.56 | -96.98 |
| US100_H1_OvernightDrift | -3.92% | -0.02 | -0.06 | -0.13 | -0.20 | -0.28 | -0.36 |

(G in basis points of log-equity per trade; negative = guaranteed long-run loss at that size.)

## 3. Closed-form P(ruin) per EA (spec formula, indicative)

P(touch −D) ≈ exp(−2·μ·D/(σ²·f²)) with μ,σ per-trade R-stats, D in R-units of equity.

| EA | f | P(touch 5% daily-line scale) | P(touch 10% max-line scale) |
|---|---|---|---|
| EURUSD_M15_LondonMomo | 0.25% | 0.000 | 0.000 |
| EURUSD_M15_LondonMomo | 0.50% | 0.018 | 0.000 |
| EURUSD_M15_LondonMomo | 0.75% | 0.069 | 0.005 |
| EURUSD_M15_LondonMomo | 1.00% | 0.135 | 0.018 |
| US500_M15_ORB | 0.25% | 1.000 | 1.000 |
| US500_M15_ORB | 0.50% | 1.000 | 1.000 |
| US500_M15_ORB | 0.75% | 1.000 | 1.000 |
| US500_M15_ORB | 1.00% | 1.000 | 1.000 |
| XAUUSD_M15_LondonFix | 0.25% | 0.000 | 0.000 |
| XAUUSD_M15_LondonFix | 0.50% | 0.003 | 0.000 |
| XAUUSD_M15_LondonFix | 0.75% | 0.022 | 0.000 |
| XAUUSD_M15_LondonFix | 1.00% | 0.057 | 0.003 |
| GBPUSD_H1_SwingBreak | 0.25% | 1.000 | 1.000 |
| GBPUSD_H1_SwingBreak | 0.50% | 1.000 | 1.000 |
| GBPUSD_H1_SwingBreak | 0.75% | 1.000 | 1.000 |
| GBPUSD_H1_SwingBreak | 1.00% | 1.000 | 1.000 |
| AUDJPY_H4_TrendFollow | 0.25% | 1.000 | 1.000 |
| AUDJPY_H4_TrendFollow | 0.50% | 1.000 | 1.000 |
| AUDJPY_H4_TrendFollow | 0.75% | 1.000 | 1.000 |
| AUDJPY_H4_TrendFollow | 1.00% | 1.000 | 1.000 |
| US100_H1_OvernightDrift | 0.25% | 1.000 | 1.000 |
| US100_H1_OvernightDrift | 0.50% | 1.000 | 1.000 |
| US100_H1_OvernightDrift | 0.75% | 1.000 | 1.000 |
| US100_H1_OvernightDrift | 1.00% | 1.000 | 1.000 |

## 4. Portfolio Monte Carlo (bootstrap of OBSERVED daily vectors, 10,000 paths × 10d, buffer ×1.6, seed 42)

### Config A — current roster (all 6 active EAs), uniform multiplier

| Multiplier (per-trade risk) | P(touch 5% daily) | P(touch 10% max) | P(recover dip→0 by d10) | P&L p5 | median | p95 |
|---|---|---|---|---|---|---|
| 1× (=0.25%/trade) | 0.00% | 0.390% | 20% | $-7,158 | $353 | $6,954 |
| 2× (=0.50%/trade) | 0.00% | 11.670% | 31% | $-14,508 | $486 | $13,772 |
| 3× (=0.75%/trade) | 64.97% | 25.180% | 34% | $-21,705 | $1,083 | $20,875 |
| 4× (=1.00%/trade) | 64.40% | 34.180% | 35% | $-29,165 | $1,763 | $27,988 |
| 5× (=1.25%/trade) | 89.61% | 43.090% | 36% | $-36,757 | $1,870 | $34,875 |

### Config B — post-cut roster (drop SwingBreak + EURUSD-chart momo leg)

| Multiplier (per-trade risk) | P(touch 5% daily) | P(touch 10% max) | P(recover dip→0 by d10) | P&L p5 | median | p95 |
|---|---|---|---|---|---|---|
| 1× (=0.25%/trade) | 0.00% | 0.010% | 28% | $-3,412 | $2,572 | $7,360 |
| 2× (=0.50%/trade) | 0.00% | 1.390% | 50% | $-6,752 | $4,916 | $14,762 |
| 3× (=0.75%/trade) | 0.00% | 6.410% | 54% | $-10,203 | $7,486 | $21,986 |
| 4× (=1.00%/trade) | 65.90% | 13.610% | 55% | $-13,210 | $9,643 | $29,017 |
| 5× (=1.25%/trade) | 64.28% | 18.210% | 60% | $-16,619 | $12,879 | $36,894 |

### Config C — tailored per-EA multipliers on the cut roster

(Carriers upsized, ambiguous EAs held at trial size; multipliers vs the 0.25% trial unit. SwingBreak + EURUSD-momo leg remain cut.)

| Config | P(touch 5% daily) | P(touch 10% max) | P(recover dip→0 by d10) | P&L p5 | median | p95 |
|---|---|---|---|---|---|---|
| C1: Momo2× Fix2× ORB1× AUDJPY1× Drift1× | 0.00% | 0.190% | 60% | $-3,314 | $6,433 | $14,895 |
| C2: Momo2× Fix2× ORB0 AUDJPY1× Drift0 | 0.00% | 0.020% | 65% | $-2,244 | $6,723 | $15,163 |
| C3: Momo3× Fix2× ORB0 AUDJPY1× Drift0 | 0.00% | 0.220% | 69% | $-2,532 | $9,422 | $20,312 |
| C4: Momo2× Fix1× ORB1× AUDJPY1× Drift1× | 0.00% | 0.080% | 56% | $-2,648 | $5,231 | $11,911 |

## 5. ERC (equal-risk-contribution) weights from daily covariance (Config B roster)

| EA (surviving roster) | inverse-vol w | ERC w | risk contribution share |
|---|---|---|---|
| EURUSD_M15_LondonMomo | 7% | 12% | 17% |
| US500_M15_ORB | 7% | 16% | 44% |
| XAUUSD_M15_LondonFix | 9% | 9% | 21% |
| AUDJPY_H4_TrendFollow | 17% | 27% | 23% |
| US100_H1_OvernightDrift | 59% | 36% | -3% |

(ERC vs inverse-vol gap = the correlation correction Baltas argues for.)
