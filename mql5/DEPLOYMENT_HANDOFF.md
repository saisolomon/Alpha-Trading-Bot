# EA Deployment -- Handoff Status (2026-05-17)

What's been deployed automatically, what remains manual, and the
sequence to start the paper-trade clock.

## What's already deployed (done from this session)

These files are now in your live MT5 data folder
(`C:\Users\saisolomon\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\`):

| File | Source | Size | Purpose |
|---|---|---|---|
| `Libraries\libquant.dll` | `cpp/build/libquant.dll` | 588 KB | C++ math + FTMO rule engine |
| `Libraries\libgcc_s_seh-1.dll` | MinGW runtime | 933 KB | Required by libquant.dll |
| `Include\QuantLib.mqh` | `mql5/Include/` | -- | DLL imports for math |
| `Include\FTMORisk.mqh` | `mql5/Include/` | -- | DLL imports for FTMO rules |
| `Experts\FTMOBot.mq5` | `mql5/Experts/` | 16 KB | EA source |
| `Experts\FTMOBot.ex5` | (compiled) | 22 KB | EA bytecode |

**Verification:**
- C++ → Python ctypes: 9/9 tests pass (`tests/test_libftmorisk_dll.py`)
- C++ → OCaml parity: 6/6 scenarios match (`tests/test_ocaml_cpp_parity.py`)
- All 6 `ftmo_*` symbols exported from `libquant.dll`
- MetaEditor compiled FTMOBot.mq5 with zero errors (one cosmetic warning
  about version string being incompatible with the MQL5 Market store --
  irrelevant for personal use)

## Remaining manual steps (GUI clicks, ~5 minutes)

Now you need to do three things inside the MT5 terminal window:

### Step 1: Enable DLL imports for EAs

In MT5: **Tools menu → Options → Expert Advisors tab**, check:
- [x] Allow algorithmic trading
- [x] Allow DLL imports

Click OK.

### Step 2: Open a chart on a tradeable index

Pick US500 (or USTEC, US30, DE40 -- the strategy targets all four; one
chart is enough for the EA to fire signals across them, but you can
attach to multiple charts if you want symbol-specific control).

In MT5: **File → New Chart → US500** (or use the Market Watch panel to
drag the symbol onto the workspace). Set the timeframe to **D1** (toolbar
or right-click → Timeframes → Daily).

### Step 3: Attach the EA

In the Navigator panel (left side, View → Navigator if hidden):
- Expand **Expert Advisors**
- Find `FTMOBot`
- **Drag it onto the chart**

A dialog appears. Configure:
- **Common tab**: ensure "Allow Algo Trading" is checked
- **Inputs tab**: defaults are fine; key settings already at the safe
  values from the backtest:
  - `InpAccountType = "CHALLENGE_2STEP_PHASE1"`
  - `InpPerTradeRiskPct = 0.005` (0.5%)
  - `InpFormationBars = 20`
  - `InpEntryZ = 1.0`
  - `InpDryRun = true`  ← **leave this true for the first day**, change
    to `false` once you've watched it log a few signals and you're
    confident the wiring is right.

Click OK. A small smiley face icon should appear in the top-right of
the chart. Click the **AutoTrading button** (the big "Algo Trading"
button in the main toolbar, should turn green).

### Step 4: Verify the EA is alive

Open the **Experts tab** at the bottom of MT5. You should see log lines
from FTMOBot like:

```
[FTMOBot] init  symbol=US500  tf=PERIOD_D1  lib=libquant 0.1.0
[FTMOBot] FTMO state initialised  balance=100000.00  handle=1
[FTMOBot] dry_run=true  risk=0.500%  formation=20  entry_z=1.00
```

If you see those, the bot is running. If you see DLL-load errors or
"function not found", come back here.

### Step 5: Set up the Windows scheduled tasks for the monitor

This is the OTHER half of the paper-trade pipeline. Open an elevated
PowerShell and run:

```powershell
cd C:\Users\saisolomon\ftmo-bot
.\scripts\setup_windows_tasks.ps1
```

This registers 4 tasks: the monitor (logon trigger, auto-restart),
hourly snapshot push, daily review at 23:30, weekly Sunday review.

Then start the monitor immediately (don't wait for next logon):

```powershell
Start-ScheduledTask -TaskName "FTMOBot Paper-Trade Monitor"
```

Within 60 seconds, `data/paper_trade/<today>.jsonl` should start
filling. Verify:

```powershell
Get-Content C:\Users\saisolomon\ftmo-bot\data\paper_trade\$((Get-Date).ToString('yyyy-MM-dd')).jsonl -Tail 2
```

## What happens next (the 4-week clock)

- **Right now → end of day 1**: EA dry-runs. Logs trades it WOULD send
  every time the signal fires. Check Experts tab once or twice to
  confirm no DLL errors.
- **End of day 1**: if logs look clean, attach the EA again with
  `InpDryRun = false`. Now it sends real orders to the demo account.
- **Daily**: monitor JSONL grows in `data/paper_trade/`, hourly push to
  GitHub, daily review at 23:30 writes a markdown report.
- **End of week 4**: aggregate the four weekly reports. If PASS criteria
  in `PAPER_TRADE_PLAN.md` are met → purchase the $25K FTMO Phase 1
  Challenge.

## If anything goes wrong

- **DLL load error in MT5 Experts tab** ("library not initialized"):
  ensure `libgcc_s_seh-1.dll` is in `MQL5\Libraries\` alongside
  `libquant.dll` -- I did this automatically but if you re-installed
  MT5 it may have been wiped.
- **Compile fails when you make a change to the EA**: re-run the
  MetaEditor compile from PowerShell (the compile_log will be in
  `MQL5\Experts\FTMOBot.compile.log`).
- **Monitor task fails to start**: check Task Scheduler GUI for the
  "FTMOBot Paper-Trade Monitor" task; logs go to `logs/`.
- **Any internal-kill event in the daily review**: STOP. Do not advance
  to a paid Challenge. Diagnose first.

## What this deployment gives you

A live MT5 EA wired to the C++ math (single source of truth with the
Python backtest, verified by 19 parity tests) and the C++ FTMO rule
engine (verified by 6 OCaml-vs-C++ parity tests and 9 ctypes smoke
tests). The bot enforces FTMO limits TICK-BY-TICK via `ftmo_apply_tick`
and gates every order through `ftmo_check_pretrade`. The Python monitor
runs the SAME risk logic in parallel as a defence-in-depth check.

Total automation: ~90% of the deployment is now automated. The 10%
remaining is the GUI clicks that genuinely require you in the MT5
window.
