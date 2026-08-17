param(
    [int]$DelayMs = 1500,
    [int]$JobTimeoutSeconds = 90
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

# Canonical single-message URLs confirmed by Basecamp's own activity mails.
$MessageA = "https://app.basecamp.com/6259481/buckets/48506183/messages/10203317150"
$MessageB = "https://app.basecamp.com/6259488/buckets/48506260/messages/10203437292"
$MessageMarkerA = "H1-A-MESSAGE-001"
$MessageMarkerB = "H1-B-MESSAGE-001"

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

    $params = @{
        Uri = "$Broker$Path"
        Method = $Method
        Headers = @{ Authorization = "Bearer $script:Token" }
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
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Marker
    )

    $response = Invoke-BrokerJson -Method POST -Path "/v1/probe-jobs" -Body @{
        client_id = $ClientId
        kind = "probe"
        url = $Url
        markers = @($Marker)
        preferred_marker = ""
    }

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
            if (-not $job.result) { throw "$Label sonucu boş." }
            if ($job.result.ok -ne $true) { throw "$Label başarısız: $($job.result.error)" }
            return $job.result
        }
        Start-Sleep -Milliseconds 700
    }

    throw "$Label timeout: $JobTimeoutSeconds saniye"
}

function Test-Marker {
    param(
        [Parameter(Mandatory)]$Result,
        [Parameter(Mandatory)][string]$Marker
    )
    return @($Result.matched_markers) -contains $Marker
}

function Invoke-ExactProbe {
    param(
        [Parameter(Mandatory)][string]$ClientId,
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Marker,
        [Parameter(Mandatory)][string]$Label
    )

    $jobId = Submit-ProbeJob -ClientId $ClientId -Url $Url -Marker $Marker
    return Wait-ProbeJob -JobId $jobId -Label $Label
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "BASECAMP MESSAGE STRICT EXACT RESOURCE AUTH MATRIX" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "A = Chrome / 6259481 / project 48506183"
Write-Host "B = Brave  / 6259488 / project 48506260"
Write-Host "Discovery yok. İki canonical /messages/<id> URL doğrudan test edilir." -ForegroundColor DarkGray
Write-Host "Yalnız navigation + DOM read; mutation yok." -ForegroundColor DarkGray

if (-not (Test-Path $Pyz)) {
    throw "Broker runtime bulunamadı: $Pyz"
}

$script:Token = Get-BridgeToken
$Sessions = Get-Sessions
$ActorA = Select-ActorSession -Sessions $Sessions -Browser "Chrome" -ProjectUrl $ProjectA
$ActorB = Select-ActorSession -Sessions $Sessions -Browser "Brave" -ProjectUrl $ProjectB

Write-Host "`n[1/4] Actor eşleşmeleri" -ForegroundColor Cyan
Write-Host "  A / Chrome -> $($ActorA.name)"
Write-Host "  B / Brave  -> $($ActorB.name)"
Write-Host "  Cookie/token değerleri loglanmıyor." -ForegroundColor DarkGray

Write-Host "`n[2/4] Project baseline..." -ForegroundColor Cyan
$ProjectResultA = Invoke-ExactProbe -ClientId $ActorA.client_id -Url $ProjectA -Marker $ProjectMarkerA -Label "A -> A project"
$ProjectResultB = Invoke-ExactProbe -ClientId $ActorB.client_id -Url $ProjectB -Marker $ProjectMarkerB -Label "B -> B project"

$ProjectPassA = Test-Marker -Result $ProjectResultA -Marker $ProjectMarkerA
$ProjectPassB = Test-Marker -Result $ProjectResultB -Marker $ProjectMarkerB

Write-Host "  A -> A marker=$ProjectPassA final=$($ProjectResultA.final_url)"
Write-Host "  B -> B marker=$ProjectPassB final=$($ProjectResultB.final_url)"

if (-not ($ProjectPassA -and $ProjectPassB)) {
    throw "PROJECT BASELINE başarısız. Exact Message/cross çalıştırılmadı."
}

Start-Sleep -Milliseconds $DelayMs

Write-Host "`n[3/4] Exact single-Message baseline..." -ForegroundColor Cyan
Write-Host "  A URL: $MessageA"
Write-Host "  B URL: $MessageB"

$MessageResultA = Invoke-ExactProbe -ClientId $ActorA.client_id -Url $MessageA -Marker $MessageMarkerA -Label "A -> A exact MESSAGE"
$MessageResultB = Invoke-ExactProbe -ClientId $ActorB.client_id -Url $MessageB -Marker $MessageMarkerB -Label "B -> B exact MESSAGE"

$MessagePassA = Test-Marker -Result $MessageResultA -Marker $MessageMarkerA
$MessagePassB = Test-Marker -Result $MessageResultB -Marker $MessageMarkerB

Write-Host "  A -> A MESSAGE marker=$MessagePassA final=$($MessageResultA.final_url)"
Write-Host "  B -> B MESSAGE marker=$MessagePassB final=$($MessageResultB.final_url)"

if (-not ($MessagePassA -and $MessagePassB)) {
    throw "EXACT MESSAGE BASELINE başarısız. Cross-account jobs oluşturulmadı."
}

Start-Sleep -Milliseconds $DelayMs

Write-Host "`n[4/4] CROSS exact single-Message matrix..." -ForegroundColor Yellow
$CrossAtoB = Invoke-ExactProbe -ClientId $ActorA.client_id -Url $MessageB -Marker $MessageMarkerB -Label "A / Chrome -> B exact MESSAGE"
$CrossBtoA = Invoke-ExactProbe -ClientId $ActorB.client_id -Url $MessageA -Marker $MessageMarkerA -Label "B / Brave -> A exact MESSAGE"

$ForeignAtoB = Test-Marker -Result $CrossAtoB -Marker $MessageMarkerB
$ForeignBtoA = Test-Marker -Result $CrossBtoA -Marker $MessageMarkerA
$Finding = $ForeignAtoB -or $ForeignBtoA

$VerdictAtoB = if ($ForeignAtoB) { "POTENTIAL_BYPASS" } else { "NO_FOREIGN_MARKER" }
$VerdictBtoA = if ($ForeignBtoA) { "POTENTIAL_BYPASS" } else { "NO_FOREIGN_MARKER" }

Write-Host ""
Write-Host "================ EXACT MESSAGE AUTH MATRIX ================" -ForegroundColor Cyan
@(
    [pscustomobject]@{ Actor = "A / Chrome"; Owner = "A"; MarkerVisible = $MessagePassA; Verdict = "BASELINE_VISIBLE"; FinalUrl = $MessageResultA.final_url },
    [pscustomobject]@{ Actor = "B / Brave"; Owner = "B"; MarkerVisible = $MessagePassB; Verdict = "BASELINE_VISIBLE"; FinalUrl = $MessageResultB.final_url },
    [pscustomobject]@{ Actor = "A / Chrome"; Owner = "B"; MarkerVisible = $ForeignAtoB; Verdict = $VerdictAtoB; FinalUrl = $CrossAtoB.final_url },
    [pscustomobject]@{ Actor = "B / Brave"; Owner = "A"; MarkerVisible = $ForeignBtoA; Verdict = $VerdictBtoA; FinalUrl = $CrossBtoA.final_url }
) | Format-Table -AutoSize

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ResultPath = Join-Path $OutDir "message-strict-exact-auto-$Stamp.json"

$Report = [ordered]@{
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    mode = "real-extension-profile-strict-exact-message-readonly"
    canonical = @{
        A = @{ url = $MessageA; marker = $MessageMarkerA }
        B = @{ url = $MessageB; marker = $MessageMarkerB }
    }
    actor_a = @{ browser = "Chrome"; client_id = $ActorA.client_id; project = $ProjectA }
    actor_b = @{ browser = "Brave"; client_id = $ActorB.client_id; project = $ProjectB }
    project_baseline = @{ A = $ProjectResultA; B = $ProjectResultB }
    message_baseline = @{ A = $MessageResultA; B = $MessageResultB }
    cross = @{ A_to_B = $CrossAtoB; B_to_A = $CrossBtoA }
    potential_authorization_bypass = $Finding
}

$Report | ConvertTo-Json -Depth 12 | Set-Content -Path $ResultPath -Encoding UTF8

Write-Host ""
if ($Finding) {
    Write-Host "POTANSİYEL AUTHORIZATION BYPASS" -ForegroundColor Red
    Write-Host "Foreign marker gerçek browser profilinde exact Message detail üzerinde görüldü." -ForegroundColor Red
} else {
    Write-Host "STRICT EXACT MESSAGE MATRIX TEMİZ" -ForegroundColor Green
    Write-Host "İki canonical /messages/<id> resource cross kontrolde de foreign marker göstermedi."
}
Write-Host "Sonuç: $ResultPath" -ForegroundColor Cyan
