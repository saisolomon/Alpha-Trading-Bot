# dataset: 84 deals -> 41 closed positions in window; 0 OUT excluded (outside window); 2 open at cutoff

## Per-EA metrics (closed positions, trial window)

| EA | Trades | W-L | Win% | AvgWin | AvgLoss | PF | MaxConsecL | AvgHold(h) | TotalP&L | $/day |
|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD_M15_LondonMomo | 11 | 7-4 | 64% | $770 | $-711 | 1.90 | 2 | 1.5 | $2,548 | $255 |
| EURUSD_M15_RSIFade | 0 | — | — | — | — | — | — | — | $0 | $0 |
| US500_M15_ORB | 5 | 2-3 | 40% | $988 | $-802 | 0.82 | 2 | 2.5 | $-429 | $-43 |
| XAUUSD_M15_LondonFix | 10 | 6-4 | 60% | $453 | $-381 | 1.78 | 1 | 2.1 | $1,194 | $119 |
| BTCUSD_M15_TrendFollow | 0 | — | — | — | — | — | — | — | $0 | $0 |
| GBPUSD_H1_SwingBreak | 8 | 1-7 | 12% | $397 | $-338 | 0.17 | 7 | 4.1 | $-1,972 | $-197 |
| XAUUSD_H1_NewsReaction | 0 | — | — | — | — | — | — | — | $0 | $0 |
| AUDJPY_H4_TrendFollow | 3 | 0-3 | 0% | — | $-387 | 0.00 | 3 | 49.9 | $-1,162 | $-116 |
| EURGBP_H4_MeanReversion | 0 | — | — | — | — | — | — | — | $0 | $0 |
| US100_H1_OvernightDrift | 4 | 1-3 | 25% | $166 | $-57 | 0.97 | 2 | 1.0 | $-5 | $-0 |

## EA × symbol split (for multi-chart EAs)

| EA | Symbol | Trades | W-L | Total P&L |
|---|---|---|---|---|
| AUDJPY_H4_TrendFollow | AUDJPY | 3 | 0-3 | $-1,162 |
| EURUSD_M15_LondonMomo | EURUSD | 4 | 2-2 | $-145 |
| EURUSD_M15_LondonMomo | GBPUSD | 7 | 5-2 | $2,693 |
| GBPUSD_H1_SwingBreak | GBPUSD | 8 | 1-7 | $-1,972 |
| US100_H1_OvernightDrift | US100 | 4 | 1-3 | $-5 |
| US500_M15_ORB | US500 | 5 | 2-3 | $-429 |
| XAUUSD_M15_LondonFix | XAUUSD | 10 | 6-4 | $1,194 |

## Closed-position ledger (in window)

| Exit (UTC) | EA | Symbol | Side | Vol | Hold(h) | P&L |
|---|---|---|---|---|---|---|
| 05-28 08:34 | GBPUSD_H1_SwingBreak | GBPUSD | SELL | 1.83 | 4.3 | $397.10 |
| 05-28 08:48 | EURUSD_M15_LondonMomo | GBPUSD | BUY | 4.68 | 0.56 | $730.08 |
| 05-28 09:14 | EURUSD_M15_LondonMomo | EURUSD | BUY | 7.71 | 0.74 | $717.02 |
| 05-28 13:51 | XAUUSD_M15_LondonFix | XAUUSD | SELL | 0.33 | 3.35 | $516.74 |
| 05-28 17:14 | AUDJPY_H4_TrendFollow | AUDJPY | SELL | 1.52 | 9.24 | $-508.75 |
| 05-28 21:00 | US100_H1_OvernightDrift | US100 | BUY | 1.50 | 1.0 | $-12.15 |
| 05-29 12:13 | XAUUSD_M15_LondonFix | XAUUSD | BUY | 0.42 | 1.72 | $516.88 |
| 05-29 23:57 | GBPUSD_H1_SwingBreak | GBPUSD | BUY | 1.73 | 5.96 | $-448.08 |
| 06-01 09:56 | EURUSD_M15_LondonMomo | GBPUSD | BUY | 6.01 | 1.69 | $745.23 |
| 06-01 10:47 | XAUUSD_M15_LondonFix | XAUUSD | BUY | 0.46 | 0.3 | $-502.00 |
| 06-01 18:23 | GBPUSD_H1_SwingBreak | GBPUSD | SELL | 1.86 | 1.39 | $-552.42 |
| 06-01 20:30 | US500_M15_ORB | US500 | SELL | 31.50 | 4.25 | $-882.00 |
| 06-01 21:00 | US100_H1_OvernightDrift | US100 | BUY | 1.90 | 1.0 | $165.68 |
| 06-02 09:21 | EURUSD_M15_LondonMomo | GBPUSD | BUY | 6.69 | 1.11 | $709.13 |
| 06-02 12:31 | XAUUSD_M15_LondonFix | XAUUSD | SELL | 0.43 | 2.03 | $498.02 |
| 06-02 16:00 | GBPUSD_H1_SwingBreak | GBPUSD | BUY | 2.71 | 6.0 | $-178.87 |
| 06-02 21:00 | US100_H1_OvernightDrift | US100 | BUY | 2.30 | 1.0 | $-138.46 |
| 06-03 11:31 | AUDJPY_H4_TrendFollow | AUDJPY | BUY | 1.37 | 111.52 | $-148.14 |
| 06-03 11:51 | XAUUSD_M15_LondonFix | XAUUSD | BUY | 0.36 | 1.36 | $-481.04 |
| 06-03 13:06 | GBPUSD_H1_SwingBreak | GBPUSD | SELL | 2.46 | 4.1 | $-263.22 |
| 06-03 16:50 | AUDJPY_H4_TrendFollow | AUDJPY | BUY | 1.55 | 28.84 | $-505.27 |
| 06-04 10:20 | EURUSD_M15_LondonMomo | GBPUSD | BUY | 5.62 | 1.1 | $-618.20 |
| 06-04 12:43 | EURUSD_M15_LondonMomo | EURUSD | BUY | 5.48 | 0.72 | $717.88 |
| 06-04 14:00 | XAUUSD_M15_LondonFix | XAUUSD | BUY | 0.43 | 3.5 | $369.69 |
| 06-04 16:00 | GBPUSD_H1_SwingBreak | GBPUSD | BUY | 2.16 | 1.0 | $-82.08 |
| 06-04 19:23 | US500_M15_ORB | US500 | BUY | 22.30 | 3.65 | $1,010.19 |
| 06-05 14:00 | XAUUSD_M15_LondonFix | XAUUSD | SELL | 0.39 | 3.5 | $-30.13 |
| 06-05 15:30 | GBPUSD_H1_SwingBreak | GBPUSD | BUY | 2.92 | 2.5 | $-321.20 |
| 06-05 16:46 | US500_M15_ORB | US500 | SELL | 39.30 | 0.77 | $966.78 |
| 06-08 09:04 | EURUSD_M15_LondonMomo | GBPUSD | SELL | 6.49 | 0.32 | $713.89 |
| 06-08 11:27 | XAUUSD_M15_LondonFix | XAUUSD | SELL | 0.25 | 0.96 | $499.75 |
| 06-08 16:34 | US500_M15_ORB | US500 | BUY | 38.20 | 0.83 | $-683.78 |
| 06-08 21:00 | US100_H1_OvernightDrift | US100 | BUY | 1.00 | 1.0 | $-20.00 |
| 06-09 11:01 | EURUSD_M15_LondonMomo | EURUSD | BUY | 4.48 | 1.77 | $-604.80 |
| 06-09 14:00 | XAUUSD_M15_LondonFix | XAUUSD | BUY | 0.41 | 3.5 | $315.67 |
| 06-09 16:00 | EURUSD_M15_LondonMomo | GBPUSD | BUY | 3.27 | 6.75 | $1,059.47 |
| 06-09 19:41 | GBPUSD_H1_SwingBreak | GBPUSD | BUY | 2.48 | 7.69 | $-523.28 |
| 06-10 11:00 | XAUUSD_M15_LondonFix | XAUUSD | BUY | 0.35 | 0.51 | $-509.90 |
| 06-10 15:26 | EURUSD_M15_LondonMomo | GBPUSD | SELL | 5.30 | 0.68 | $-646.60 |
| 06-10 15:30 | EURUSD_M15_LondonMomo | EURUSD | SELL | 8.19 | 1.0 | $-974.62 |
| 06-10 18:52 | US500_M15_ORB | US500 | BUY | 15.70 | 3.12 | $-839.95 |

## Daily realized P&L by EA (rows=EA, cols=days)

| EA | 05-28 | 05-29 | 06-01 | 06-02 | 06-03 | 06-04 | 06-05 | 06-08 | 06-09 | 06-10 | TOTAL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD_M15_LondonMomo | 1,447 | · | 745 | 709 | · | 100 | · | 714 | 455 | -1,621 | 2,548 |
| US500_M15_ORB | · | · | -882 | · | · | 1,010 | 967 | -684 | · | -840 | -429 |
| XAUUSD_M15_LondonFix | 517 | 517 | -502 | 498 | -481 | 370 | -30 | 500 | 316 | -510 | 1,194 |
| GBPUSD_H1_SwingBreak | 397 | -448 | -552 | -179 | -263 | -82 | -321 | · | -523 | · | -1,972 |
| AUDJPY_H4_TrendFollow | -509 | · | · | · | -653 | · | · | · | · | · | -1,162 |
| US100_H1_OvernightDrift | -12 | · | 166 | -138 | · | · | · | -20 | · | · | -5 |
| **PORTFOLIO** | 1,840 | 69 | -1,026 | 890 | -1,398 | 1,397 | 615 | 510 | 247 | -2,971 | 174 |

## Cross-EA daily P&L correlation (Pearson, zeros included; n=10 days -- SMALL SAMPLE)

| | EURUSD_LondonMo | US500_ORB | XAUUSD_LondonFi | GBPUSD_SwingBre | AUDJPY_TrendFol | US100_Overnigh |
|---|---|---|---|---|---|---|
| EURUSD_LondonMo | 1.00 | +0.09 | +0.54 | +0.14 | -0.25 | -0.01 |
| US500_ORB | +0.09 | 1.00 | +0.34 | +0.01 | -0.03 | -0.31 |
| XAUUSD_LondonFi | +0.54 | +0.34 | 1.00 | +0.28 | +0.19 | -0.57 |
| GBPUSD_SwingBre | +0.14 | +0.01 | +0.28 | 1.00 | -0.40 | -0.38 |
| AUDJPY_TrendFol | -0.25 | -0.03 | +0.19 | -0.40 | 1.00 | +0.03 |
| US100_Overnigh | -0.01 | -0.31 | -0.57 | -0.38 | +0.03 | 1.00 |

## Cluster-day event study (the 3 USD-rip days vs all other days)

| EA | Cluster-days P&L | Other-days P&L | Cluster share of EA total loss |
|---|---|---|---|
| EURUSD_M15_LondonMomo | $-876 | $3,424 | 54% |
| US500_M15_ORB | $-1,722 | $1,293 | 72% |
| XAUUSD_M15_LondonFix | $-1,493 | $2,687 | 98% |
| GBPUSD_H1_SwingBreak | $-816 | $-1,156 | 34% |
| AUDJPY_H4_TrendFollow | $-653 | $-509 | 56% |
| US100_H1_OvernightDrift | $166 | $-171 | — |
| **PORTFOLIO** | $-5,394 | $5,569 | |

## Factor exposure: daily EA P&L vs DXY daily return (single-factor OLS; n is TINY -- indicative only)

common days with DXY data: 10 of 10

| EA | β(DXY) $ per +1% DXY | α $/day | R² | n |
|---|---|---|---|---|
| EURUSD_M15_LondonMomo | $-766 | $316 | 0.07 | 10 |
| US500_M15_ORB | $346 | $-71 | 0.02 | 10 |
| XAUUSD_M15_LondonFix | $-1,088 | $207 | 0.41 | 10 |
| GBPUSD_H1_SwingBreak | $-377 | $-167 | 0.12 | 10 |
| AUDJPY_H4_TrendFollow | $-20 | $-115 | 0.00 | 10 |
| US100_H1_OvernightDrift | $75 | $-7 | 0.08 | 10 |
| **PORTFOLIO** | $-1,830 | $164 | 0.12 | 10 |

## Measured costs (exact, from deals)

| Symbol | Closed trades | Total commission | Total swap |
|---|---|---|---|
| AUDJPY | 3 | $-22.22 | $26.71 |
| EURUSD | 4 | $-129.32 | $0.00 |
| GBPUSD | 15 | $-281.12 | $0.00 |
| US100 | 4 | $0.00 | $0.00 |
| US500 | 5 | $0.00 | $0.00 |
| XAUUSD | 10 | $-23.71 | $0.00 |

NOTE: bid/ask spread cost is embedded in realized P&L and NOT separable from deal records alone (requires requested-vs-filled prices). Fix queued: OnTradeTransaction upgrade (M10) captures both prices going forward.
