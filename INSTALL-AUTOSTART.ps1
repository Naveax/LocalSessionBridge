$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$Pyz = Join-Path $Root "dist\session-bridge-v1.0.0.pyz"
$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument ('"{0}" serve --quiet' -f $Pyz) -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "UniversalLocalSessionBridge" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Local-only browser session broker" -Force | Out-Null
Write-Host "Autostart kuruldu: UniversalLocalSessionBridge"
