# Gold-Silver Pairs EA -- Deployment Handoff

The second alpha leg (gold-silver cointegration pairs) is now built and
compiled. Adding it to your live MT5 alongside the existing US500_MeanRev
takes ~5 minutes and requires one MT5 restart so the new libquant.dll
can replace the one currently loaded.

## Why a restart is needed

The running US500_MeanRev has `libquant.dll` loaded in-memory and Windows
won't let us overwrite the file while it's locked. The new
`libquant.dll` has all the old exports PLUS `quant_rolling_ols` (the
new function the pairs EA needs). Without the new DLL the pairs EA will
fail at runtime with "function not found".

## The 5-minute deployment

### Step 1: clean stop the current bot (~30 sec)

In MT5:
- **Right-click the chart** that has US500_MeanRev attached
- **Expert Advisors → Remove**
- Confirm. The smiley face disappears.

Optionally also note any open positions; US500_MeanRev was in dry-run mode so
there shouldn't be any.

### Step 2: close MT5 fully (~10 sec)

**File → Exit** (or just close the window with X). Confirm if asked.
Verify the system tray icon is gone.

### Step 3: replace the DLL (one PowerShell command)

```powershell
Copy-Item C:\Users\saisolomon\ftmo-bot\cpp\build\libquant.dll `
          C:\Users\saisolomon\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Libraries\libquant.dll `
          -Force
```

Should complete instantly with no error.

### Step 4: re-open MT5 and re-attach both EAs (~2 min)

Launch MT5 again. Log back into the demo account if it doesn't auto-login.

Then attach BOTH EAs:

**EA #1 -- US500_MeanRev (the index mean-reversion bot, already-running strategy):**
- Open a US500 D1 chart (File → New Chart → US500, set timeframe to D1)
- Drag `US500_MeanRev` from Navigator → Expert Advisors onto the chart
- Inputs: leave defaults (`InpDryRun=true` if still validating, or
  `false` if you'd already flipped it)
- OK. Confirm smiley appears.

**EA #2 -- XAUUSD_XAGUSD_Pairs (the NEW gold-silver pairs bot):**
- Open a XAUUSD D1 chart (File → New Chart → XAUUSD, timeframe D1)
- Drag `XAUUSD_XAGUSD_Pairs` from Navigator → Expert Advisors onto the chart
- Inputs (defaults are fine):
  - `InpSymbolA = "XAUUSD"`
  - `InpSymbolB = "XAGUSD"`
  - `InpEntryZ = 2.5`        (only opens on extreme spread deviations)
  - `InpExitZ = 0.5`
  - `InpCatastrophicZ = 5.0`
  - `InpMaxHoldBars = 60`    (~3 months max hold for the pair)
  - `InpPerTradeRiskPct = 0.005`  (0.5% on the spread's worst-case move)
  - `InpDryRun = true`       (LEAVE TRUE for the first 24h to verify wiring)
- OK. Second smiley appears on the XAUUSD chart.

### Step 5: re-arm AutoTrading

Click **AutoTrading** button (should already be green from before, but
confirm). Both EAs now operate independently:
- US500_MeanRev fires Index MR signals across US500/USTEC/US30/DE40
- XAUUSD_XAGUSD_Pairs fires pairs trades on XAUUSD/XAGUSD when the
  cointegration spread hits z = +/-2.5

### Step 6: verify in the Experts log (~30 sec)

Bottom of MT5, Experts tab. You should see TWO init blocks:

```
[US500_MeanRev] init  symbol=US500  tf=PERIOD_D1  lib=libquant 0.1.0
[US500_MeanRev] FTMO state initialised  balance=...  handle=1
[US500_MeanRev] dry_run=true  risk=0.500%  formation=20  entry_z=1.00

[XAUUSD_XAGUSD_Pairs] init  pair=XAUUSD-XAGUSD  lib=libquant 0.1.0
[XAUUSD_XAGUSD_Pairs] FTMO state init  balance=...  handle=2
                       dry_run=true  entry_z=2.50 exit_z=0.50 cat_z=5.00 risk=0.50%
```

If you see both, the deployment is complete. The bot now runs both legs
of the proven 2-strategy portfolio.

## What to expect

The gold-silver pair has a long half-life (~123 D1 bars = ~6 months).
On the 12y backtest it fired only 14 trades total, so:
- **Many weeks may pass with zero pairs activity** -- this is correct
  and expected
- When it does fire, it'll open BOTH legs simultaneously (one long, one
  short, dollar-neutral)
- Expected holding time per trade: 1-3 months
- Max hold (time stop): 60 D1 bars = ~3 months

Sharpe contribution at the standalone level is only +0.22, but the
correlation with the Index MR leg is essentially zero (-0.019), which
is why the COMBINED portfolio Sharpe lifts from 0.48 to 0.51 with
MaxDD cut nearly in half (5.08% -> 2.35%).

## Monitor doesn't need any changes

The paper-trade monitor already captures `mt5.positions_get()` which
returns all positions regardless of symbol. When XAUUSD_XAGUSD_Pairs opens a
XAUUSD + XAGUSD pair, those positions automatically show up in the
JSONL snapshots. The daily review reports include them in the open-
positions table.

## After 24h of dry-run

Same as US500_MeanRev: open the XAUUSD_XAGUSD_Pairs inputs (right-click chart ->
Expert Advisors -> Properties), flip `InpDryRun` to `false`, OK. Now
real pair orders fire.

## What this changes for the 4-week paper-trade

Your **deployed Sharpe target is now 0.51** (the equal-weight portfolio),
not the standalone 0.48 of Index MR alone. The PASS criteria in
`PAPER_TRADE_PLAN.md` still apply at the portfolio level. The
combined-portfolio Sharpe and MaxDD will both be reported in the
weekly tracking-error review.

## If anything goes wrong

- **"XAUUSD_XAGUSD_Pairs cannot find function quant_rolling_ols"** -> the new
  libquant.dll didn't get copied. Close MT5, re-run the copy in step 3,
  re-open.
- **Pairs EA errors on init with "Cannot find symbol XAUUSD"** -> the
  symbol isn't in MarketWatch. In MT5: View → Market Watch (Ctrl+M),
  right-click → Show all, find XAUUSD and XAGUSD, drag them into
  the visible list.
- **Pairs EA fires a trade but only one leg fills** -> the broker
  rejected the second leg (likely volume too small). The EA logs the
  retcode; check the journal. Worst case: manually close the orphan
  leg in MT5 and tell me.
