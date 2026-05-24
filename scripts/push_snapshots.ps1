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
    # Capture stderr+stdout so failures are diagnosable in the log.
    # Previous version used `2>&1 | Out-Null` which silently discarded
    # the real git error and left only the "To <url>" echo line, making
    # every failure look identical and untriageable.
    $addOut = git add data/paper_trade/ 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git add failed: $addOut" }

    $today = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
    $commitOut = git commit -m "paper-trade snapshots $today" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git commit failed: $commitOut" }

    $pushOut = git push 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git push failed: $pushOut" }

    Log "pushed snapshots OK"
} catch {
    # Single-line, log-friendly version of the multi-line error
    $err = ($_.ToString() -replace "`r?`n", " | ")
    Log "ERROR: $err"
    exit 1
}
