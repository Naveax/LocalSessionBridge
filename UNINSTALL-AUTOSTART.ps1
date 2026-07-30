$ErrorActionPreference = "Stop"
Unregister-ScheduledTask -TaskName "UniversalLocalSessionBridge" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Autostart kaldırıldı."
