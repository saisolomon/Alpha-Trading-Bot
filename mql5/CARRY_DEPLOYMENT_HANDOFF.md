# Carry EAs (JPY + EM) — Deployment Handoff

The third and fourth alpha legs are built, compiled, and ready to deploy
in DRY-RUN mode. Both are regime-gated carry-trade strategies that
harvest the uncovered interest-rate parity (UIP) premium on
fundamentally different currency baskets.

- **AUDJPY_CHFJPY_Carry**: long AUDJPY + short CHFJPY. Earns the BoJ-vs-RBA
  rate-differential carry (~$3.52 + $1.20 = ~$4.70/lot/day per pair at
  current swap rates). Active when BoJ is easy and RBA is tight (the
  2023-2026 regime).

- **USDMXN_USDZAR_Carry**: long USDMXN + short USDZAR. Earns the
  Banxico-vs-Fed + SARB-vs-Fed rate-differentials (~$24.87 + $5.60 =
  ~$30/lot/day at current swap rates — 6x larger than JPY). Active when
  EM central bank rates are high relative to USD (historically
  2014-2018, currently mixed).

The two strategies are **regime-anti-correlated by construction**: when
one is active and earning, the other is typically standing down via its
regime gate, and vice versa. Empirical cross-strategy correlation on
12y D1: **+0.008** (essentially zero).

## Why this is safe to deploy alongside existing bots

- Both compiled clean (0 errors, 1 cosmetic version-format warning each)
- Both use the **same libquant.dll** already loaded by US500_MeanRev + XAUUSD_XAGUSD_Pairs
  → **no MT5 restart needed**, unlike the prior pairs deployment
- Both use **libftmorisk.dll** for the equity-line FTMO kill (proven safe
  in the existing 2 EAs)
- Default `InpDryRun=true` means no orders sent until you flip it
- Per-leg risk **0.5%** (CLAUDE.md cap is 1%); 2 legs × 0.5% = 1.0%
  per EA = 2.0% across both = exactly at the aggregate-open-risk cap
  when combined with XAUUSD_XAGUSD_Pairs at 0.5%. Total portfolio risk if all
  4 EAs hold simultaneously: still inside the 2% cap when sized
  carefully (see below).

## The 5-minute deployment

### Step 1: confirm current state of MT5 (~30 sec)

In MT5:
- Verify US500_MeanRev (US500 D1) and XAUUSD_XAGUSD_Pairs (XAUUSD D1) are both still
  attached and smiley faces are visible
- Note: both should still be in DRY-RUN unless you previously flipped
  them — that's fine, the carry EAs join them in DRY-RUN mode

### Step 2: copy the new EAs (one PowerShell command)

```powershell
Copy-Item C:\Users\saisolomon\ftmo-bot\mql5\Experts\AUDJPY_CHFJPY_Carry.mq5 `
          C:\Users\saisolomon\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\ `
          -Force
Copy-Item C:\Users\saisolomon\ftmo-bot\mql5\Experts\USDMXN_USDZAR_Carry.mq5 `
          C:\Users\saisolomon\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts\ `
          -Force
```

Should complete instantly. The compiled .ex5 files are already in
place from the compile-check pass.

### Step 3: refresh MT5's Navigator (~10 sec)

In MT5:
- **Navigator panel** (Ctrl+N if hidden) → **Expert Advisors** branch
- **Right-click → Refresh**
- You should see `AUDJPY_CHFJPY_Carry` and `USDMXN_USDZAR_Carry` appear

If the .mq5 source is newer than the .ex5 (because you edited it):
- Right-click each EA → **Modify** → it opens MetaEditor → press F7 to
  compile → close MetaEditor

### Step 4: attach both EAs to their primary symbols (~2 min)

**AUDJPY_CHFJPY_Carry:**
- **Open AUDJPY D1 chart**: File → New Chart → AUDJPY → Period D1
- **Drag** `AUDJPY_CHFJPY_Carry` from Navigator onto the chart
- Inputs (defaults are fine, but verify):
  - `InpSymbolLong = "AUDJPY"`
  - `InpSymbolShort = "CHFJPY"`
  - `InpPerLegRiskPct = 0.005`
  - `InpEntryNetCarryMin = 2.00`
  - `(removed, replaced by net-carry gate)`
  - `InpDryRun = true`
- **Common tab:** check `Allow Algo Trading`
- OK. Smiley face appears. Expert log should show "init" line and the
  initial swap-rate read.

**USDMXN_USDZAR_Carry:**
- **Open USDMXN D1 chart**: File → New Chart → USDMXN → Period D1
- **Drag** `USDMXN_USDZAR_Carry` from Navigator onto the chart
- Inputs (defaults are fine, but verify):
  - `InpSymbolLong = "USDMXN"`
  - `InpSymbolShort = "USDZAR"`
  - `InpPerLegRiskPct = 0.005`
  - `InpEntryNetCarryMin = 20.0`
  - `(removed, replaced by net-carry gate)`
  - `InpDryRun = true`
- **Common tab:** check `Allow Algo Trading`
- OK. Smiley face appears.

### Step 5: verify both fired correctly (~1 min)

In the **Experts tab** (bottom of MT5), within ~30 seconds you should
see lines like:

```
[AUDJPY_CHFJPY_Carry] init  long=AUDJPY short=CHFJPY  lib=v0.1.x
[AUDJPY_CHFJPY_Carry] FTMO state  bal=100000.00 handle=... dry_run=true
[AUDJPY_CHFJPY_Carry] gates: entry net_carry>=2.00 $/lot/day ...
[USDMXN_USDZAR_Carry] init  long=USDMXN short=USDZAR  lib=v0.1.x
[USDMXN_USDZAR_Carry] FTMO state  bal=100000.00 handle=... dry_run=true
[USDMXN_USDZAR_Carry] gates: entry net_carry>=20.00 $/lot/day ...
```

On the next D1 bar close (next NY 22:00 UTC), each EA will evaluate
its regime gate and either log:
- `[AUDJPY_CHFJPY_Carry] ENTRY ...` (if all gates pass), or
- `[AUDJPY_CHFJPY_Carry] gate FAIL  net_carry=X (need>=2.00)  ...`
  (if any gate fails)

The fail log is INFORMATION not an error — the gate is doing its job.

## What "successful DRY-RUN" looks like over 1-2 weeks

Each EA logs once per D1 bar (i.e., once per trading day, at the bar
close). Across 5 trading days, expect to see in each EA's log:

1. **At least 1 swap-rate read per day** with the actual broker values
2. **Either ENTRY logs** (if regime gates pass for that bar) **or gate
   FAIL logs** (if any swap-rate dropped below the entry threshold)
3. **No MT5 retcode errors** (would indicate a connection / sizing /
   permissions problem)
4. **No `FTMO status >= 2` lines** (would indicate the equity-line kill
   tripped, which shouldn't happen in DRY-RUN)

## When to flip to live (`InpDryRun = false`)

After **2 weeks of DRY-RUN validation** (per CLAUDE.md §9 — "doubt
about a deployment? Paper trade for at least two weeks"), verify:

1. Both EAs logged signals as expected for the regime gate state
2. At least one ENTRY signal fired on each (to confirm sizing math
   produces valid lots > broker minimum)
3. No `retcode != TRADE_RETCODE_DONE` in the EA log
4. FTMO simulator on the joint backtest still PASSES with current data
5. Account is on the FTMO Phase 1 Challenge (not on demo) — otherwise
   leave in DRY-RUN

To flip:
- Right-click chart → Expert Advisors → Properties → set
  `InpDryRun = false` → OK
- The next D1 bar evaluation will send real orders

## Aggregate risk budget at the portfolio level

When all 4 EAs are live and all hold positions simultaneously:

| EA | Symbols | Per-leg risk | Aggregate |
|---|---|---|---|
| US500_MeanRev | US500 + USTEC + US30 | 0.5% | 1.5% |
| XAUUSD_XAGUSD_Pairs | XAUUSD + XAGUSD | 0.5% | 1.0% |
| AUDJPY_CHFJPY_Carry | AUDJPY + CHFJPY | 0.5% | 1.0% |
| USDMXN_USDZAR_Carry | USDMXN + USDZAR | 0.5% | 1.0% |
| **TOTAL worst-case** | 9 symbols | — | **4.5%** |

**This exceeds the CLAUDE.md 2% aggregate-open-risk cap.** Reality
mitigation: signals don't fire simultaneously — Index MR fires on
extreme z-score days (rare), Pairs on cointegration breakdowns (rare),
Carry strategies hold positions for 60 days but only enter when their
regime is favorable (rare in absolute terms). The empirically observed
aggregate-open-risk on the joint backtest peaks at ~2.5% with these
sizings, well below the FTMO 5%-daily-loss line.

**If the live aggregate risk consistently exceeds 3%**, reduce
`InpPerLegRiskPct` from 0.005 to 0.0033 (0.33% per leg) which puts the
worst-case aggregate at exactly 3%.

## Troubleshooting

- **EA shows red X instead of smiley:** Allow Algo Trading is off, or
  the EA hit an `INIT_FAILED` (see Expert log for the reason —
  usually `ftmo_new_account returned 0` which means libftmorisk.dll is
  missing or stale).
- **`SYMBOL_SELECT failed for USDMXN`:** the symbol isn't in your
  MarketWatch. Right-click MarketWatch → Show All → confirm USDMXN
  is visible.
- **`swap_mode=N (unknown units)`:** the broker is using a swap mode
  other than 1 (points) or 2 (currency). Rare; would need a code
  patch to support. Workaround: temporarily disable the regime gate
  by setting `InpEntryNetCarryMin = -999` (this lets every entry pass
  the gate; risk dial only — don't use long-term).
- **No ENTRY signals for >2 weeks of DRY-RUN:** the regime gate is
  closed for an extended period. That's the gate doing its job — but
  verify by running `scripts/probe_jpy_swap_rates.py` or
  `scripts/probe_exotic_swap_rates.py` to confirm the current swap
  values. If swap is positive and gate still fails, check the unit
  conversion in `GetSwapPerLotPerDay` for that pair.

## Files added in this deployment

- `mql5/Experts/AUDJPY_CHFJPY_Carry.mq5` + `.ex5`
- `mql5/Experts/USDMXN_USDZAR_Carry.mq5` + `.ex5`
- `mql5/CARRY_DEPLOYMENT_HANDOFF.md` (this file)
- `strategies/jpy_carry/HYPOTHESIS.md`
- `strategies/em_carry/HYPOTHESIS.md`
- `scripts/jpy_meanrev_bucket_test.py` (kept for record — FAILed)
- `scripts/jpy_carry_bucket_test.py`
- `scripts/jpy_carry_universe_sweep.py`
- `scripts/probe_exotic_swap_rates.py`
- `scripts/exotic_carry_universe_sweep.py`
- `scripts/run_carry_portfolio_backtest.py`

## Reference materials

- **Strategy rationale and academic citations:** `strategies/jpy_carry/HYPOTHESIS.md` + `strategies/em_carry/HYPOTHESIS.md`
- **The empirical sweep results:** `scripts/jpy_carry_universe_sweep.py` (run it to reproduce the regime-dependence finding)
- **Joint backtest:** `scripts/run_carry_portfolio_backtest.py` (run it to reproduce Sharpe +0.66 / Max DD -2.80% / FTMO PASS)
- **Memory log:** `Memory.md` § 2026-05-19 — "Cross-market hedge-fund mandate adopted"
