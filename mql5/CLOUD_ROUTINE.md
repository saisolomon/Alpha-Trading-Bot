# Cloud Routine -- 4-Week Paper-Trade Monitoring

How to run the 4-week paper-trade validation with a cloud-hosted Claude
routine handling daily review, while your local Windows machine does the
actual monitoring.

## Why two tiers?

MT5 has to be running on your Windows desktop -- it's where the bot
trades. A cloud routine can't operate MT5 directly. The split:

| Component | Where | Cadence | Job |
|---|---|---|---|
| MT5 terminal + FTMOBot EA | Local Windows | continuous | Trade |
| `paper_trade_monitor.py`  | Local Windows | continuous | Snapshot every 60s |
| `push_snapshots.ps1`      | Local Windows | hourly task | Commit + push snapshots to git |
| `cloud_daily_review.py`   | Claude routine | daily 22:30 UTC | Pull, review, commit report |
| `cloud_weekly_review.py`  | Claude routine | Sunday 22:30 UTC | Weekly tracking-error review |

## Prerequisites

1. **A git remote** (GitHub / GitLab / Gitea). Add it once:
   ```powershell
   git remote add origin git@github.com:YOUR-ORG/ftmo-bot.git
   git push -u origin master
   ```

2. **Build the C++ DLL once** (per `cpp/README.md`) and **OCaml lib once**
   (per `ocaml/README.md`). The cloud doesn't rebuild these -- it runs
   the Python paper-trade review scripts only.

3. **Deploy the EA** per `mql5/PAPER_TRADE_PLAN.md` (copy DLLs +
   FTMOBot.mq5 into the MT5 data folder, F7 in MetaEditor, attach to a
   D1 chart, AutoTrading ON, `InpDryRun=false`).

## Local-side setup (one time, on the Windows host)

### 1. Start the monitor (foreground for the first day so you can verify it works)

```powershell
cd C:\Users\saisolomon\ftmo-bot
uv run python scripts/paper_trade_monitor.py --poll-seconds 60
```

Check that `data/paper_trade/<today>.jsonl` is growing.

### 2. Install the monitor as a Windows scheduled task (so it survives restarts)

From an **elevated PowerShell**:

```powershell
$cmd = "C:\Users\saisolomon\.local\bin\uv.exe"
$args = "run python C:\Users\saisolomon\ftmo-bot\scripts\paper_trade_monitor.py --poll-seconds 60"

$action = New-ScheduledTaskAction -Execute $cmd -Argument $args -WorkingDirectory C:\Users\saisolomon\ftmo-bot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "FTMOBot Paper-Trade Monitor" `
    -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest
```

### 3. Install the hourly snapshot push

From elevated PowerShell:

```powershell
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Users\saisolomon\ftmo-bot\scripts\push_snapshots.ps1"
$trigger = New-ScheduledTaskTrigger -Once `
    -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "FTMOBot Paper-Trade Push" `
    -Action $action -Trigger $trigger -RunLevel Highest
```

### 4. Verify

After 90 minutes:
- `data/paper_trade/<today>.jsonl` exists and has ~90 snapshots
- `git log --oneline -5` shows commits like "paper-trade snapshots YYYY-MM-DD"
- The remote has the snapshots: `git log origin/master --oneline -5`

## Cloud-routine setup (via `/schedule` in Claude Code)

Once `/schedule` is back, create **two routines** with these specs:

### Routine 1: Daily review

**Cron:** `30 22 * * *`  (22:30 UTC every day, ~midnight Prague in winter)
**Title:** `FTMOBot daily paper-trade review`
**Prompt:**
```
You are running the daily paper-trade review for the FTMO bot.

1. `git pull` to fetch the latest snapshots the local monitor pushed.
2. Run: `uv run python scripts/cloud_daily_review.py --days 1`
3. The script writes reports/paper_trade/<today>.md and prints it to
   stdout. Capture the verdict line ("OK", "WARN", or "FAIL").
4. If the script exit code is 2 (FAIL -- internal kill), notify me
   immediately with the report markdown in the chat.
5. If exit code is 1 (WARN -- data gaps), notify with the gap details.
6. If exit code is 0 (OK), commit the report to git:
     git add reports/paper_trade/
     git commit -m "daily review <today>"
     git push
   Then post a one-line summary in chat: "[OK] daily review <today>: 
   <pnl_pct>%, <n_snapshots> snapshots, no kills."

The PAPER_TRADE_PLAN.md in this repo is the authoritative spec for what
"clean" means -- consult it if anything looks off.
```

### Routine 2: Weekly tracking-error review

**Cron:** `30 22 * * 0`  (22:30 UTC every Sunday)
**Title:** `FTMOBot weekly paper-trade review`
**Prompt:**
```
You are running the weekly tracking-error review for the FTMO bot.

1. `git pull` for the latest snapshots.
2. Run: `uv run python scripts/cloud_weekly_review.py`
3. The script writes reports/paper_trade/week_ending_<date>.md and
   exits 0 (OK), 1 (WARN, > 2 sigma), or 2 (FAIL, > 3 sigma or kill).
4. Always notify me with the verdict line + the full report body.
5. Commit the report:
     git add reports/paper_trade/
     git commit -m "weekly review <date>"
     git push

The pass/fail criteria in mql5/PAPER_TRADE_PLAN.md govern whether we
can proceed to a paid FTMO Challenge at the end of week 4.
```

## Running the 4-week clock

- **Week 0** (right now): set up the local monitor + push, verify
  snapshots are flowing for 24h.
- **Week 1**: enable the cloud routines via `/schedule`. Daily reviews
  start arriving.
- **Weeks 2-4**: cloud routine runs nightly + Sunday weekly review.
  Human reviews the daily summaries; intervenes only on FAIL.
- **End of week 4**: take the four weekly review reports + the final
  daily report. Apply the pass/fail criteria from `PAPER_TRADE_PLAN.md`.
  If PASS -> purchase a $25K 2-Step Phase 1 Challenge.

## What to do if the routine FAILs

- **Internal-kill triggered**: stop trading immediately on the local
  EA (just remove it from the chart). Diagnose: was the kill triggered
  by the strategy itself (the position sizing is too aggressive), by a
  monitor bug (the FTMO state machine misread the equity), or by an
  actual bad fill on a gap?
- **Tracking error > 3 sigma**: review the trade log against
  `scripts/run_meanrev_backtest.py`'s output on the same date range.
  Where did the divergence start?
- **Data gap > 4h**: check MT5 terminal stayed running; check Windows
  didn't reboot for an update. Re-fetch the missed bars and rerun the
  monitor on them to backfill if possible.

## Manual fallback (no /schedule)

If `/schedule` stays unavailable, you can run the same logic locally
via Windows Task Scheduler:

```powershell
# Daily review at 22:30 UTC = 17:30 EST = 23:30 CET (winter)
$action = New-ScheduledTaskAction `
    -Execute "C:\Users\saisolomon\.local\bin\uv.exe" `
    -Argument "run python scripts/cloud_daily_review.py" `
    -WorkingDirectory "C:\Users\saisolomon\ftmo-bot"
$trigger = New-ScheduledTaskTrigger -Daily -At 22:30
Register-ScheduledTask -TaskName "FTMOBot Daily Review" `
    -Action $action -Trigger $trigger -RunLevel Highest
```

That gives the same result minus the chat notifications.
