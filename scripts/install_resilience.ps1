# install_resilience.ps1
# One-time install of the "FTMOBot won't go silent" safety net.
#
# Run ONCE from an ELEVATED PowerShell window:
#   Right-click PowerShell → Run as Administrator
#   cd C:\Users\saisolomon\ftmo-bot
#   .\scripts\install_resilience.ps1
#
# What this does:
#
# OPTION 1 — disable system sleep on AC power
#   Without this, Windows suspends MT5 + the monitor whenever you step
#   away. While suspended, no heartbeats reach Convex and you'll get
#   Pushover alerts every time the machine sleeps for >10 minutes.
#
#   We disable standby + hibernate but leave the monitor (display)
#   timeout alone -- the screen can still sleep, just not the CPU.
#
# OPTION 3 — replace the paper_trade_monitor scheduled task
#   The previous task triggered only "At logon time" with no
#   restart-on-failure. If Windows rebooted while you weren't watching,
#   or if the monitor process crashed, it stayed dead.
#
#   New config:
#     - Triggers: AtLogon + every 5 minutes thereafter
#     - MultipleInstances=IgnoreNew so duplicate triggers don't spawn
#       a second monitor (which would double-post to Convex)
#     - RestartCount=10 RestartInterval=5min for crash recovery
#     - ExecutionTimeLimit=0 so the task doesn't get killed at 72h
#     - Battery-tolerant so it survives a brief unplug
#
# After this runs you should NOT see "heartbeat stale" Pushover alerts
# unless something real is broken (broker down, internet out, MT5
# closed, hardware failure).

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

Write-Host "============================================================"
Write-Host "  FTMOBot resilience installer"
Write-Host "============================================================"
Write-Host ""

# --------------------------------------------------------------------
# OPTION 1: disable system sleep
# --------------------------------------------------------------------
Write-Host "[Option 1] Disabling system sleep..."
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
# We deliberately do NOT change monitor-timeout-ac -- screen can sleep,
# system cannot. Saves power without breaking the monitor.
$standby = (powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE | Select-String "Current AC Power Setting").Line
Write-Host "  $standby"
Write-Host "  done."
Write-Host ""

# --------------------------------------------------------------------
# OPTION 3: hardened scheduled task
# --------------------------------------------------------------------
$taskName = "FTMOBot Paper-Trade Monitor"
$repoRoot = "C:\Users\saisolomon\ftmo-bot"
$uvExe    = "C:\Users\saisolomon\.local\bin\uv.exe"

Write-Host "[Option 3] Reconfiguring scheduled task '$taskName'..."

# Verify uv.exe exists; abort with a clear message if not.
if (-not (Test-Path $uvExe)) {
    throw "uv.exe not found at $uvExe. Find your uv install with 'where.exe uv' and update the script."
}
if (-not (Test-Path $repoRoot)) {
    throw "Repo not found at $repoRoot. Update the script."
}

# Stop + remove any existing task
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    try { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue } catch {}
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "  removed old task."
}

# Kill any orphan python.exe instances running the monitor (so the new
# task doesn't end up running alongside a manually-started copy and
# double-posting to Convex).
$monitorProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*paper_trade_monitor*" }
foreach ($p in $monitorProcs) {
    Write-Host "  killing orphan monitor PID $($p.ProcessId)..."
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($monitorProcs) { Start-Sleep -Seconds 1 }  # let ports release

# Build new task spec
$action = New-ScheduledTaskAction `
    -Execute $uvExe `
    -Argument "run python scripts/paper_trade_monitor.py --poll-seconds 60" `
    -WorkingDirectory $repoRoot

# Trigger 1: at user logon
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Trigger 2: every 5 minutes for the next ~27 years
# (RepetitionDuration must be a positive TimeSpan; we use 10000 days as
#  "effectively forever" since [TimeSpan]::MaxValue has known issues
#  with COM serialization.)
$intervalTrigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 10000)

# Settings: restart on failure, single instance, bounded execution time
# CHANGED 2026-05-25: was ExecutionTimeLimit=0 (unlimited). When the
# monitor python crashed but its parent process stayed alive, Task
# Scheduler kept seeing the task as "Running" -> blocked all retries
# with ERROR_SERVICE_ALREADY_RUNNING (-2147020576). Setting a 4-hour
# limit forces stuck instances to be killed, freeing the trigger to
# spawn a fresh instance on the next 5-min interval.
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

# Run as the current user, interactive (needs to connect to MT5 GUI
# session, so SYSTEM/SERVICE wouldn't work).
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Description "FTMOBot monitor: auto-starts at logon, retries every 5min, restarts on failure. Installed by install_resilience.ps1." `
    -Action $action `
    -Trigger @($logonTrigger, $intervalTrigger) `
    -Settings $settings `
    -Principal $principal | Out-Null

Write-Host "  registered new task."

# Fire it immediately so user doesn't have to wait for the next trigger
Start-ScheduledTask -TaskName $taskName
Write-Host "  started monitor."
Write-Host ""

Write-Host "============================================================"
Write-Host "  Done."
Write-Host "============================================================"
Write-Host ""
Write-Host "Verify within ~90 seconds:"
Write-Host "  - check https://clever-malamute-966.convex.site/ shows"
Write-Host "    heartbeat age < 90s in the dashboard"
Write-Host "  - or run:"
Write-Host "    Get-ScheduledTaskInfo -TaskName '$taskName' | Format-List"
Write-Host ""
Write-Host "If the monitor doesn't start, check the Task Scheduler GUI"
Write-Host "(Win+R -> taskschd.msc) for the task's last-run result code."
