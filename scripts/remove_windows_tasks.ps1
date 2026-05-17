# remove_windows_tasks.ps1
# Removes all four FTMOBot scheduled tasks. Run from elevated PowerShell.

$names = @(
    "FTMOBot Paper-Trade Monitor",
    "FTMOBot Paper-Trade Push",
    "FTMOBot Daily Review",
    "FTMOBot Weekly Review"
)

foreach ($n in $names) {
    $task = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if ($task) {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false
        Write-Host "Removed: $n" -ForegroundColor Green
    } else {
        Write-Host "Not found (already removed): $n" -ForegroundColor Yellow
    }
}
