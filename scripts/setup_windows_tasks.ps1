# setup_windows_tasks.ps1
# One-shot Windows Task Scheduler setup for the 4-week paper-trade run.
# Run ONCE from an elevated PowerShell (Right-click PowerShell -> Run as Administrator).
#
# Registers four scheduled tasks:
#   1. FTMOBot Paper-Trade Monitor   -- runs paper_trade_monitor.py at logon, auto-restart
#   2. FTMOBot Paper-Trade Push      -- pushes snapshots to git every hour
#   3. FTMOBot Daily Review          -- runs cloud_daily_review.py at 23:30 local (~midnight Prague in winter)
#   4. FTMOBot Weekly Review         -- runs cloud_weekly_review.py on Sundays
#
# To remove later: run remove_windows_tasks.ps1 (or use Task Scheduler GUI).

$ErrorActionPreference = "Stop"

$repoRoot = "C:\Users\saisolomon\ftmo-bot"
$uvPath   = "C:\Users\saisolomon\.local\bin\uv.exe"

# Sanity
if (-not (Test-Path $repoRoot)) { throw "Repo root not found: $repoRoot" }
if (-not (Test-Path $uvPath))   { throw "uv.exe not found: $uvPath" }

Write-Host "Registering 4 scheduled tasks for the FTMO paper-trade run..." -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------
# 1. Paper-Trade Monitor (continuous, runs at logon)
# ---------------------------------------------------------------
$task1Name = "FTMOBot Paper-Trade Monitor"
Write-Host "1/4  $task1Name"
$action1 = New-ScheduledTaskAction `
    -Execute $uvPath `
    -Argument "run python scripts/paper_trade_monitor.py --poll-seconds 60" `
    -WorkingDirectory $repoRoot
$trigger1 = New-ScheduledTaskTrigger -AtLogOn
$settings1 = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $task1Name `
    -Action $action1 -Trigger $trigger1 -Settings $settings1 `
    -RunLevel Highest -Force | Out-Null
Write-Host "      OK -- will start at logon, auto-restart on failure (5 min interval, max 99 tries)"

# ---------------------------------------------------------------
# 2. Hourly snapshot push
# ---------------------------------------------------------------
$task2Name = "FTMOBot Paper-Trade Push"
Write-Host "2/4  $task2Name"
$action2 = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File $repoRoot\scripts\push_snapshots.ps1"
$trigger2 = New-ScheduledTaskTrigger `
    -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $task2Name `
    -Action $action2 -Trigger $trigger2 `
    -RunLevel Highest -Force | Out-Null
Write-Host "      OK -- pushes snapshots to git every hour"

# ---------------------------------------------------------------
# 3. Daily review (local fallback for the cloud routine)
# ---------------------------------------------------------------
$task3Name = "FTMOBot Daily Review"
Write-Host "3/4  $task3Name"
$action3 = New-ScheduledTaskAction `
    -Execute $uvPath `
    -Argument "run python scripts/cloud_daily_review.py --days 1" `
    -WorkingDirectory $repoRoot
# Daily at 23:30 local time. This is approximately Prague midnight in winter
# (CET = UTC+1) and ~1h after Prague midnight in summer (CEST = UTC+2).
$trigger3 = New-ScheduledTaskTrigger -Daily -At "23:30"
Register-ScheduledTask -TaskName $task3Name `
    -Action $action3 -Trigger $trigger3 `
    -RunLevel Highest -Force | Out-Null
Write-Host "      OK -- runs daily at 23:30 local time, writes reports/paper_trade/<date>.md"

# ---------------------------------------------------------------
# 4. Weekly review (Sundays)
# ---------------------------------------------------------------
$task4Name = "FTMOBot Weekly Review"
Write-Host "4/4  $task4Name"
$action4 = New-ScheduledTaskAction `
    -Execute $uvPath `
    -Argument "run python scripts/cloud_weekly_review.py" `
    -WorkingDirectory $repoRoot
$trigger4 = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Sunday -At "23:30"
Register-ScheduledTask -TaskName $task4Name `
    -Action $action4 -Trigger $trigger4 `
    -RunLevel Highest -Force | Out-Null
Write-Host "      OK -- runs Sundays at 23:30 local time, writes weekly tracking-error report"

Write-Host ""
Write-Host "All 4 tasks registered." -ForegroundColor Green
Write-Host ""
Write-Host "Verification commands:" -ForegroundColor Yellow
Write-Host "  Get-ScheduledTask FTMOBot* | Format-Table TaskName, State"
Write-Host "  Get-ScheduledTaskInfo (Get-ScheduledTask 'FTMOBot Paper-Trade Monitor')"
Write-Host ""
Write-Host "To remove all four later:" -ForegroundColor Yellow
Write-Host "  Get-ScheduledTask FTMOBot* | Unregister-ScheduledTask -Confirm:`$false"
Write-Host ""
Write-Host "Next step: start the Monitor task NOW (it normally only starts at next logon):" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName 'FTMOBot Paper-Trade Monitor'"
