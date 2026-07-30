$ErrorActionPreference = "Stop"
$Path = Join-Path $env:LOCALAPPDATA "UniversalLocalSessionBridge"
if (Test-Path -LiteralPath $Path) {
    Remove-Item -LiteralPath $Path -Recurse -Force
}
Write-Host "Yerel veriler silindi: $Path"
