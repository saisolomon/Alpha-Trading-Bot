# push_snapshots.ps1
# Local-side scheduled task: commit and push the latest paper-trade
# snapshots to git, hourly. The cloud routine pulls these and runs the
# daily/weekly review.
#
# Install as a Windows scheduled task (one-time, from an elevated
# PowerShell):
#
#   $action = New-ScheduledTaskAction `
#       -Execute "powershell.exe" `
#       -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Users\saisolomon\ftmo-bot\scripts\push_snapshots.ps1"
#   $trigger = New-ScheduledTaskTrigger -Once `
#       -At (Get-Date) `
#       -RepetitionInterval (New-TimeSpan -Hours 1)
#   Register-ScheduledTask -TaskName "FTMOBot Paper-Trade Push" `
#       -Action $action -Trigger $trigger -RunLevel Highest

$ErrorActionPreference = "Stop"
Set-Location C:\Users\saisolomon\ftmo-bot

$logFile = "logs\push_snapshots.log"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

function Log($msg) {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    "[$ts] $msg" | Tee-Object -FilePath $logFile -Append
}

try {
    Log "starting push"
    # Only act if there are snapshot changes
    $changed = git status --porcelain data/paper_trade/ 2>$null
    if (-not $changed) {
        Log "no new snapshots to push"
        exit 0
    }
    git add data/paper_trade/ 2>&1 | Out-Null
    $today = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
    git commit -m "paper-trade snapshots $today" 2>&1 | Out-Null
    git push 2>&1 | Out-Null
    Log "pushed snapshots OK"
} catch {
    Log "ERROR: $_"
    exit 1
}
