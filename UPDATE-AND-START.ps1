param(
    [switch]$SkipPull,
    [switch]$SkipBrowserPages
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Resolve-Python {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Python bulunamadı."
}

function Open-ExtensionPages {
    $braveCandidates = @(
        "$env:ProgramFiles\BraveSoftware\Brave-Browser\Application\brave.exe",
        "${env:ProgramFiles(x86)}\BraveSoftware\Brave-Browser\Application\brave.exe",
        "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe"
    )
    $chromeCandidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )

    $brave = $braveCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    $chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($brave) { Start-Process $brave "brave://extensions" }
    if ($chrome) { Start-Process $chrome "chrome://extensions" }
}

$python = Resolve-Python
$pyz = Join-Path $Root "dist\session-bridge-v1.0.0.pyz"

Write-Host "`n[1/6] LocalSessionBridge" -ForegroundColor Cyan
Write-Host "Root: $Root"

if (-not $SkipPull) {
    Write-Host "`n[2/6] GitHub main güncelleniyor..." -ForegroundColor Cyan
    & git -C $Root pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull başarısız oldu." }
} else {
    Write-Host "`n[2/6] Git pull atlandı." -ForegroundColor DarkGray
}

Write-Host "`n[3/6] Release artifactleri yeniden oluşturuluyor..." -ForegroundColor Cyan
& $python (Join-Path $Root "scripts\build_release.py")
if ($LASTEXITCODE -ne 0) { throw "build_release.py başarısız oldu." }
if (-not (Test-Path $pyz)) { throw "Broker artifact bulunamadı: $pyz" }

Write-Host "`n[4/6] Eski broker kapatılıyor..." -ForegroundColor Cyan
$brokers = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -and
        $_.CommandLine -match 'session-bridge-v1\.0\.0\.pyz' -and
        $_.CommandLine -match '\bserve\b'
    }

foreach ($proc in $brokers) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

Write-Host "`n[5/6] Broker başlatılıyor..." -ForegroundColor Cyan
Start-Process -FilePath $python -ArgumentList @("`"$pyz`"", "serve", "--quiet") -WorkingDirectory $Root -WindowStyle Hidden

$ready = $false
1..20 | ForEach-Object {
    if ($ready) { return }
    Start-Sleep -Milliseconds 300
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:17871/v1/health" -TimeoutSec 2
        if ($health.ok) { $ready = $true }
    } catch {}
}
if (-not $ready) { throw "Broker 127.0.0.1:17871 üzerinde READY olmadı." }

$pairCode = (& $python $pyz pair-code | Out-String).Trim()
Set-Clipboard -Value $pairCode

Write-Host "`n[6/6] Hazır." -ForegroundColor Green
Write-Host "Broker: http://127.0.0.1:17871" -ForegroundColor Green
Write-Host "Fresh pair code: $pairCode" -ForegroundColor Yellow
Write-Host "Pair code panoya kopyalandı." -ForegroundColor DarkGray

if (-not $SkipBrowserPages) {
    Open-ExtensionPages
}

Write-Host ""
Write-Host "Brave/Chrome extensions sayfasında Local Session Bridge için bir kez Reload'a bas." -ForegroundColor Yellow
Write-Host "Yeni popup'ta site bazlı Aç/Kapat, Tümünü aç/kapat/eşitle, tarayıcı/profil, cookie sayısı, son sync, keep-alive ve hata bilgileri görünür." -ForegroundColor Green
Write-Host "Kapalı kayıtlar otomatik sync ve keep-alive çalıştırmaz." -ForegroundColor Green
