param(
    [int]$DelayMs = 1200,
    [int]$JobTimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = (Get-Command python -ErrorAction Stop).Source
$Pyz = Join-Path $Root "dist\session-bridge-v1.0.0.pyz"
$Broker = "http://127.0.0.1:17871"
$OutDir = Join-Path $Root "basecamp-auth-results"

$ProjectA = "https://app.basecamp.com/6259481/projects/48506183"
$ProjectB = "https://app.basecamp.com/6259488/projects/48506260"
$ProjectMarkerA = "H1-AUTH-A-PROJECT"
$ProjectMarkerB = "H1-AUTH-B-PROJECT"
$TodoMarkerA = "H1-A-TODO-001"
$TodoMarkerB = "H1-B-TODO-001"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Get-BridgeToken {
    $value = (& $Python $Pyz token | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $value) {
        throw "LocalSessionBridge API token alınamadı."
    }
    return $value
}

function Invoke-BrokerJson {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        $Body = $null
    )

    $headers = @{ Authorization = "Bearer $script:Token" }
    $params = @{
        Uri = "$Broker$Path"
        Method = $Method
        Headers = $headers
    }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = ($Body | ConvertTo-Json -Depth 10 -Compress)
    }
    return Invoke-RestMethod @params
}

function Get-Sessions {
    return @((Invoke-BrokerJson -Method GET -Path "/v1/sessions").sessions)
}

function Select-ActorSession {
    param(
        [Parameter(Mandatory)]$Sessions,
        [Parameter(Mandatory)][string]$Browser,
        [Parameter(Mandatory)][string]$ProjectUrl
    )

    $session = $Sessions |
        Where-Object {
            $_.browser -eq $Browser -and
            $_.url -eq $ProjectUrl -and
            $_.status -eq "READY"
        } |
        Sort-Object updated_at -Descending |
        Select-Object -First 1

    if (-not $session) {
        throw "READY actor session bulunamadı: $Browser / $ProjectUrl"
    }
    return $session
}

function Submit-ProbeJob {
    param(
        [Parameter(Mandatory)][string]$ClientId,
        [Parameter(Mandatory)][string]$Kind,
        [Parameter(Mandatory)][string]$Url,
        [string[]]$Markers = @(),
        [string]$PreferredMarker = ""
    )

    $body = @{
        client_id = $ClientId
        kind = $Kind
        url = $Url
        markers = @($Markers)
        preferred_marker = $PreferredMarker
    }

    $response = Invoke-BrokerJson -Method POST -Path "/v1/probe-jobs" -Body $body
    if (-not $response.job_id) {
        throw "Probe job oluşturulamadı."
    }
    return [string]$response.job_id
}

function Wait-ProbeJob {
    param(
        [Parameter(Mandatory)][string]$JobId,
        [Parameter(Mandatory)][string]$Label
    )

    $deadline = (Get-Date).AddSeconds($JobTimeoutSeconds)
    $lastStatus = ""

    while ((Get-Date) -lt $deadline) {
        $job = Invoke-BrokerJson -Method GET -Path "/v1/probe-jobs/$JobId"
        if ($job.status -ne $lastStatus) {
            Write-Host "  $Label -> $($job.status)" -ForegroundColor DarkGray
            $lastStatus = [string]$job.status
        }
        if ($job.status -eq "DONE") {
            if (-not $job.result) {
                throw "$Label sonucu boş."
            }
            if ($job.result.ok -ne $true) {
                throw "$Label başarısız: $($job.result.error)"
            }
            return $job.result
        }
        Start-Sleep -Milliseconds 750
    }

    throw "$Label timeout: $JobTimeoutSeconds saniye"
}

function Test-MarkerMatch {
    param(
        [Parameter(Mandatory)]$Result,
        [Parameter(Mandatory)][string]$Marker
    )
    return @($Result.matched_markers) -contains $Marker
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "BASECAMP TODO BROWSER-NATIVE FULL-AUTO AUTH MATRIX" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "A = Chrome / 6259481 / project 48506183"
Write-Host "B = Brave  / 6259488 / project 48506260"
Write-Host "Hedefte yalnız navigation/DOM read var; mutation yok." -ForegroundColor DarkGray

if (-not (Test-Path $Pyz)) {
    throw "Broker runtime bulunamadı: $Pyz"
}

$script:Token = Get-BridgeToken
$Sessions = Get-Sessions
$ActorA = Select-ActorSession -Sessions $Sessions -Browser "Chrome" -ProjectUrl $ProjectA
$ActorB = Select-ActorSession -Sessions $Sessions -Browser "Brave" -ProjectUrl $ProjectB

Write-Host "`n[1/5] Actor eşleşmeleri" -ForegroundColor Cyan
Write-Host "  A / Chrome -> $($ActorA.name)"
Write-Host "  B / Brave  -> $($ActorB.name)"
Write-Host "  Cookie/token değerleri loglanmıyor." -ForegroundColor DarkGray

Write-Host "`n[2/5] Project baseline işleri gönderiliyor..." -ForegroundColor Cyan
$ProjectJobA = Submit-ProbeJob -ClientId $ActorA.client_id -Kind "probe" -Url $ProjectA -Markers @($ProjectMarkerA)
$ProjectJobB = Submit-ProbeJob -ClientId $ActorB.client_id -Kind "probe" -Url $ProjectB -Markers @($ProjectMarkerB)

$ProjectResultA = Wait-ProbeJob -JobId $ProjectJobA -Label "A -> A project"
$ProjectResultB = Wait-ProbeJob -JobId $ProjectJobB -Label "B -> B project"

$ProjectPassA = Test-MarkerMatch -Result $ProjectResultA -Marker $ProjectMarkerA
$ProjectPassB = Test-MarkerMatch -Result $ProjectResultB -Marker $ProjectMarkerB

Write-Host "  A -> A marker=$ProjectPassA final=$($ProjectResultA.final_url)"
Write-Host "  B -> B marker=$ProjectPassB final=$($ProjectResultB.final_url)"

if (-not ($ProjectPassA -and $ProjectPassB)) {
    throw "PROJECT BASELINE başarısız. To-do discovery/cross çalıştırılmadı."
}

Start-Sleep -Milliseconds $DelayMs

Write-Host "`n[3/5] To-do kaynakları gerçek Chrome/Brave profillerinde keşfediliyor..." -ForegroundColor Cyan
$DiscoverJobA = Submit-ProbeJob -ClientId $ActorA.client_id -Kind "discover_todo" -Url $ProjectA -PreferredMarker $TodoMarkerA
$DiscoverJobB = Submit-ProbeJob -ClientId $ActorB.client_id -Kind "discover_todo" -Url $ProjectB -PreferredMarker $TodoMarkerB

$TodoA = Wait-ProbeJob -JobId $DiscoverJobA -Label "A todo discovery"
$TodoB = Wait-ProbeJob -JobId $DiscoverJobB -Label "B todo discovery"

if (-not $TodoA.found_url -or -not $TodoA.marker) { throw "A To-do keşfi eksik sonuç döndürdü." }
if (-not $TodoB.found_url -or -not $TodoB.marker) { throw "B To-do keşfi eksik sonuç döndürdü." }

Write-Host "  A TODO: $($TodoA.marker)" -ForegroundColor Green
Write-Host "          $($TodoA.found_url)"
Write-Host "          source=$($TodoA.source)" -ForegroundColor DarkGray
Write-Host "  B TODO: $($TodoB.marker)" -ForegroundColor Green
Write-Host "          $($TodoB.found_url)"
Write-Host "          source=$($TodoB.source)" -ForegroundColor DarkGray

Start-Sleep -Milliseconds $DelayMs

Write-Host "`n[4/5] Resource baseline..." -ForegroundColor Cyan
$TodoBaselineJobA = Submit-ProbeJob -ClientId $ActorA.client_id -Kind "probe" -Url $TodoA.found_url -Markers @([string]$TodoA.marker)
$TodoBaselineJobB = Submit-ProbeJob -ClientId $ActorB.client_id -Kind "probe" -Url $TodoB.found_url -Markers @([string]$TodoB.marker)

$TodoBaselineA = Wait-ProbeJob -JobId $TodoBaselineJobA -Label "A -> A TODO"
$TodoBaselineB = Wait-ProbeJob -JobId $TodoBaselineJobB -Label "B -> B TODO"

$TodoPassA = Test-MarkerMatch -Result $TodoBaselineA -Marker ([string]$TodoA.marker)
$TodoPassB = Test-MarkerMatch -Result $TodoBaselineB -Marker ([string]$TodoB.marker)

Write-Host "  A -> A TODO marker=$TodoPassA final=$($TodoBaselineA.final_url)"
Write-Host "  B -> B TODO marker=$TodoPassB final=$($TodoBaselineB.final_url)"

if (-not ($TodoPassA -and $TodoPassB)) {
    throw "TODO BASELINE başarısız. Cross-account jobs bilinçli olarak oluşturulmadı."
}

Start-Sleep -Milliseconds $DelayMs

Write-Host "`n[5/5] CROSS read-only To-do matrix..." -ForegroundColor Yellow
$CrossJobAtoB = Submit-ProbeJob -ClientId $ActorA.client_id -Kind "probe" -Url $TodoB.found_url -Markers @([string]$TodoB.marker)
$CrossJobBtoA = Submit-ProbeJob -ClientId $ActorB.client_id -Kind "probe" -Url $TodoA.found_url -Markers @([string]$TodoA.marker)

$CrossAtoB = Wait-ProbeJob -JobId $CrossJobAtoB -Label "A / Chrome -> B TODO"
$CrossBtoA = Wait-ProbeJob -JobId $CrossJobBtoA -Label "B / Brave -> A TODO"

$ForeignVisibleAtoB = Test-MarkerMatch -Result $CrossAtoB -Marker ([string]$TodoB.marker)
$ForeignVisibleBtoA = Test-MarkerMatch -Result $CrossBtoA -Marker ([string]$TodoA.marker)
$Finding = $ForeignVisibleAtoB -or $ForeignVisibleBtoA

$VerdictAtoB = if ($ForeignVisibleAtoB) { "POTENTIAL_BYPASS" } else { "NO_FOREIGN_MARKER" }
$VerdictBtoA = if ($ForeignVisibleBtoA) { "POTENTIAL_BYPASS" } else { "NO_FOREIGN_MARKER" }

Write-Host ""
Write-Host "================ TODO AUTH MATRIX ================" -ForegroundColor Cyan
[pscustomobject]@{ Actor = "A / Chrome"; Owner = "A"; MarkerVisible = $TodoPassA; Verdict = "BASELINE_VISIBLE"; FinalUrl = $TodoBaselineA.final_url },
[pscustomobject]@{ Actor = "B / Brave"; Owner = "B"; MarkerVisible = $TodoPassB; Verdict = "BASELINE_VISIBLE"; FinalUrl = $TodoBaselineB.final_url },
[pscustomobject]@{ Actor = "A / Chrome"; Owner = "B"; MarkerVisible = $ForeignVisibleAtoB; Verdict = $VerdictAtoB; FinalUrl = $CrossAtoB.final_url },
[pscustomobject]@{ Actor = "B / Brave"; Owner = "A"; MarkerVisible = $ForeignVisibleBtoA; Verdict = $VerdictBtoA; FinalUrl = $CrossBtoA.final_url } |
    Format-Table -AutoSize

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ResultPath = Join-Path $OutDir "todo-browser-native-auto-$Stamp.json"
$Report = [ordered]@{
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    mode = "real-extension-profile-readonly"
    actor_a = @{ browser = "Chrome"; client_id = $ActorA.client_id; project = $ProjectA }
    actor_b = @{ browser = "Brave"; client_id = $ActorB.client_id; project = $ProjectB }
    todo_a = $TodoA
    todo_b = $TodoB
    project_baseline = @{ A = $ProjectResultA; B = $ProjectResultB }
    todo_baseline = @{ A = $TodoBaselineA; B = $TodoBaselineB }
    cross = @{ A_to_B = $CrossAtoB; B_to_A = $CrossBtoA }
    potential_authorization_bypass = $Finding
}
$Report | ConvertTo-Json -Depth 12 | Set-Content -Path $ResultPath -Encoding UTF8

Write-Host ""
if ($Finding) {
    Write-Host "POTANSİYEL AUTHORIZATION BYPASS" -ForegroundColor Red
    Write-Host "Foreign To-do marker gerçek browser profilinin DOM'unda görüldü." -ForegroundColor Red
    Write-Host "Burada dur. Mutation/checkbox/POST/PATCH/DELETE yapma." -ForegroundColor Yellow
}
else {
    Write-Host "READ-ONLY TODO MATRIX TEMİZ" -ForegroundColor Green
    Write-Host "Her iki cross kontrolde de foreign To-do marker görünmedi."
}

Write-Host "Sonuç: $ResultPath" -ForegroundColor Cyan
