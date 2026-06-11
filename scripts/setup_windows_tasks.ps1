# setup_windows_tasks.ps1
# One-shot Windows Task Scheduler setup for the paper-trade / dry-run stack.
# Run ONCE from an elevated PowerShell (Right-click PowerShell -> Run as Administrator).
#
# Registers (default):
#   1. FTMOBot Paper-Trade Monitor   -- paper_trade_monitor.py; at-logon + every 5 min,
#                                       ExecutionTimeLimit 4h, MultipleInstances=IgnoreNew
#   2. FTMOBot Paper-Trade Push      -- pushes snapshots to git every hour
# With -IncludeReviews, additionally:
#   3. FTMOBot Daily Review          -- cloud_daily_review.py at 23:30 local
#   4. FTMOBot Weekly Review         -- cloud_weekly_review.py on Sundays
#
# 2026-06-11 rework (VPS migration, runbook §6):
#   - Paths derived from the script's own location -- works on the old box
#     (C:\Users\saisolomon\ftmo-bot) and the VPS (C:\ftmo-bot) unchanged.
#   - Monitor runs .venv python directly (no uv.exe dependency at task runtime).
#   - Monitor redesign per the 6/10 hung-instance lesson: the old at-logon +
#     RestartCount design could not recycle a HUNG (not crashed) instance because
#     ExecutionTimeLimit was Zero. New design: a 5-min repeating trigger with
#     IgnoreNew acts as a watchdog -- if the instance is alive the fire is ignored;
#     if it died, the next fire restarts it (max 5-min gap); if it hangs, the 4h
#     limit kills it and the next fire restarts it.
#   - Tasks run with the interactive token ("run only when user is logged on").
#     This is DELIBERATE: the MetaTrader5 Python API attaches to the terminal in
#     the SAME session; a cross-session task would silently launch a second
#     terminal instance. Pair with Windows auto-logon so reboots land in a
#     logged-on console session (RDP-disconnect keeps the session alive).
#
# To remove later: run remove_windows_tasks.ps1 (or use Task Scheduler GUI).

param(
    [switch]$IncludeReviews
)

$ErrorActionPreference = "Stop"

$repoRoot   = Split-Path $PSScriptRoot -Parent
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

# Sanity
if (-not (Test-Path $repoRoot))   { throw "Repo root not found: $repoRoot" }
if (-not (Test-Path $venvPython)) { throw ".venv python not found: $venvPython (run 'uv sync' first)" }

$total = if ($IncludeReviews) { 4 } else { 2 }
Write-Host "Registering $total scheduled tasks for the FTMO stack (repo: $repoRoot)..." -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------
# 1. Paper-Trade Monitor (at logon + 5-min watchdog repetition)
# ---------------------------------------------------------------
$task1Name = "FTMOBot Paper-Trade Monitor"
Write-Host "1/$total  $task1Name"
$action1 = New-ScheduledTaskAction `
    -Execute $venvPython `
    -Argument "scripts\paper_trade_monitor.py --poll-seconds 60" `
    -WorkingDirectory $repoRoot
$trigger1a = New-ScheduledTaskTrigger -AtLogOn
$trigger1b = New-ScheduledTaskTrigger `
    -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings1 = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)
Register-ScheduledTask -TaskName $task1Name `
    -Action $action1 -Trigger $trigger1a, $trigger1b -Settings $settings1 `
    -RunLevel Highest -Force | Out-Null
Write-Host "      OK -- at-logon + 5-min watchdog fire (IgnoreNew), 4h recycle limit"

# ---------------------------------------------------------------
# 2. Hourly snapshot push
# ---------------------------------------------------------------
$task2Name = "FTMOBot Paper-Trade Push"
Write-Host "2/$total  $task2Name"
$action2 = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\scripts\push_snapshots.ps1`""
$trigger2 = New-ScheduledTaskTrigger `
    -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $task2Name `
    -Action $action2 -Trigger $trigger2 `
    -RunLevel Highest -Force | Out-Null
Write-Host "      OK -- pushes snapshots to git every hour"

if ($IncludeReviews) {
    # -----------------------------------------------------------
    # 3. Daily review (local fallback for the cloud routine)
    # -----------------------------------------------------------
    $task3Name = "FTMOBot Daily Review"
    Write-Host "3/$total  $task3Name"
    $action3 = New-ScheduledTaskAction `
        -Execute $venvPython `
        -Argument "scripts\cloud_daily_review.py --days 1" `
        -WorkingDirectory $repoRoot
    $trigger3 = New-ScheduledTaskTrigger -Daily -At "23:30"
    Register-ScheduledTask -TaskName $task3Name `
        -Action $action3 -Trigger $trigger3 `
        -RunLevel Highest -Force | Out-Null
    Write-Host "      OK -- runs daily at 23:30 local time"

    # -----------------------------------------------------------
    # 4. Weekly review (Sundays)
    # -----------------------------------------------------------
    $task4Name = "FTMOBot Weekly Review"
    Write-Host "4/$total  $task4Name"
    $action4 = New-ScheduledTaskAction `
        -Execute $venvPython `
        -Argument "scripts\cloud_weekly_review.py" `
        -WorkingDirectory $repoRoot
    $trigger4 = New-ScheduledTaskTrigger `
        -Weekly -DaysOfWeek Sunday -At "23:30"
    Register-ScheduledTask -TaskName $task4Name `
        -Action $action4 -Trigger $trigger4 `
        -RunLevel Highest -Force | Out-Null
    Write-Host "      OK -- runs Sundays at 23:30 local time"
}

Write-Host ""
Write-Host "All $total tasks registered." -ForegroundColor Green
Write-Host ""
Write-Host "Verification commands:" -ForegroundColor Yellow
Write-Host "  Get-ScheduledTask FTMOBot* | Format-Table TaskName, State"
Write-Host "  Get-ScheduledTaskInfo (Get-ScheduledTask 'FTMOBot Paper-Trade Monitor')"
Write-Host ""
Write-Host "To remove all later:" -ForegroundColor Yellow
Write-Host "  Get-ScheduledTask FTMOBot* | Unregister-ScheduledTask -Confirm:`$false"
Write-Host ""
Write-Host "Next step: start the Monitor task NOW (or wait <=5 min for the watchdog fire):" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName 'FTMOBot Paper-Trade Monitor'"
