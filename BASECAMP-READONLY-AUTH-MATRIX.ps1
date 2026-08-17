param(
    [int]$DelayMs = 1200,
    [int]$MaxRedirects = 8
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = (Get-Command python -ErrorAction Stop).Source
$Pyz = Join-Path $Root "dist\session-bridge-v1.0.0.pyz"
$Broker = "http://127.0.0.1:17871"

$Actors = @{
    A = [pscustomobject]@{
        Label      = "A / Chrome"
        Browser    = "Chrome"
        ProjectUrl = "https://app.basecamp.com/6259481/projects/48506183"
        Marker     = "H1-AUTH-A-PROJECT"
    }
    B = [pscustomobject]@{
        Label      = "B / Brave"
        Browser    = "Brave"
        ProjectUrl = "https://app.basecamp.com/6259488/projects/48506260"
        Marker     = "H1-AUTH-B-PROJECT"
    }
}

$AllowedOrigins = @{
    "https://app.basecamp.com" = $true
    "https://launchpad.37signals.com" = $true
}

function Get-Origin {
    param([Parameter(Mandatory)][string]$Url)
    return ([uri]$Url).GetLeftPart([System.UriPartial]::Authority)
}

function Get-BridgeToken {
    $value = (& $Python $Pyz token | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $value) {
        throw "LocalSessionBridge API token alınamadı."
    }
    return $value
}

function Get-BridgeSessions {
    param([Parameter(Mandatory)][string]$Token)

    $response = Invoke-RestMethod `
        -Uri "$Broker/v1/sessions" `
        -Headers @{ Authorization = "Bearer $Token" } `
        -Method GET

    return @($response.sessions)
}

function Select-PrimarySession {
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
        throw "READY primary session bulunamadı: $Browser / $ProjectUrl"
    }

    return $session
}

function Select-OriginSession {
    param(
        [Parameter(Mandatory)]$Sessions,
        [Parameter(Mandatory)][string]$ClientId,
        [Parameter(Mandatory)][string]$Origin
    )

    return $Sessions |
        Where-Object {
            if ($_.client_id -ne $ClientId -or $_.status -ne "READY") {
                return $false
            }
            try {
                return (Get-Origin $_.url) -eq $Origin
            }
            catch {
                return $false
            }
        } |
        Sort-Object updated_at -Descending |
        Select-Object -First 1
}

function Get-BridgeCookieHeader {
    param(
        [Parameter(Mandatory)][string]$SessionName,
        [Parameter(Mandatory)][string]$TargetUrl
    )

    $value = (
        & $Python $Pyz get $SessionName --header-only --url $TargetUrl 2>$null |
        Out-String
    ).Trim()

    if ($LASTEXITCODE -ne 0 -or -not $value) {
        throw "Cookie header üretilemedi: $SessionName -> $TargetUrl"
    }

    return $value
}

function Add-BridgeCookiesToJar {
    param(
        [Parameter(Mandatory)][System.Net.CookieContainer]$Jar,
        [Parameter(Mandatory)][string]$TargetUrl,
        [Parameter(Mandatory)][string]$CookieHeader
    )

    $uri = [uri]$TargetUrl

    foreach ($part in ($CookieHeader -split ';\s*')) {
        if (-not $part) { continue }
        $splitAt = $part.IndexOf('=')
        if ($splitAt -le 0) { continue }

        $name = $part.Substring(0, $splitAt).Trim()
        $value = $part.Substring($splitAt + 1)
        if (-not $name) { continue }

        try {
            $cookie = [System.Net.Cookie]::new($name, $value, "/", $uri.Host)
            $cookie.Secure = ($uri.Scheme -eq "https")
            $Jar.Add($uri, $cookie)
        }
        catch {
            throw "Cookie jar seed başarısız: $name / $($uri.Host)"
        }
    }
}

function Resolve-RedirectUrl {
    param(
        [Parameter(Mandatory)][string]$CurrentUrl,
        [Parameter(Mandatory)][string]$Location
    )

    return ([uri]::new([uri]$CurrentUrl, $Location)).AbsoluteUri
}

function Get-SecFetchSite {
    param(
        [string]$PreviousUrl,
        [Parameter(Mandatory)][string]$CurrentUrl
    )

    if (-not $PreviousUrl) { return "none" }
    if ((Get-Origin $PreviousUrl) -eq (Get-Origin $CurrentUrl)) {
        return "same-origin"
    }
    return "cross-site"
}

function New-ChainResult {
    param(
        [string]$Actor,
        [string]$Owner,
        [string]$StartUrl,
        [string]$FinalUrl,
        [int]$Status,
        [bool]$MarkerVisible,
        [string]$Verdict,
        $Hops
    )

    return [pscustomobject]@{
        Actor         = $Actor
        Owner         = $Owner
        StartUrl      = $StartUrl
        FinalUrl      = $FinalUrl
        Status        = $Status
        MarkerVisible = $MarkerVisible
        Verdict       = $Verdict
        HopCount      = @($Hops).Count
        Hops          = @($Hops)
    }
}

function Invoke-BrowserLikeReadonlyGet {
    param(
        [Parameter(Mandatory)][string]$Actor,
        [Parameter(Mandatory)][string]$Owner,
        [Parameter(Mandatory)][string]$StartUrl,
        [Parameter(Mandatory)][string]$ExpectedMarker,
        [Parameter(Mandatory)][string]$ClientId,
        [Parameter(Mandatory)]$Sessions
    )

    # Fresh jar per matrix cell. Baseline state can never bleed into cross tests.
    $jar = [System.Net.CookieContainer]::new()
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $true
    $handler.CookieContainer = $jar
    $handler.AutomaticDecompression =
        [System.Net.DecompressionMethods]::GZip -bor
        [System.Net.DecompressionMethods]::Deflate -bor
        [System.Net.DecompressionMethods]::Brotli

    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(30)

    $currentUrl = $StartUrl
    $previousUrl = ""
    $hops = @()
    $seededOrigins = @{}

    try {
        for ($index = 0; $index -le $MaxRedirects; $index++) {
            $origin = Get-Origin $currentUrl

            if (-not $AllowedOrigins.ContainsKey($origin)) {
                return New-ChainResult -Actor $Actor -Owner $Owner -StartUrl $StartUrl `
                    -FinalUrl $currentUrl -Status 0 -MarkerVisible $false `
                    -Verdict "UNSUPPORTED_ORIGIN" -Hops $hops
            }

            $session = Select-OriginSession -Sessions $Sessions -ClientId $ClientId -Origin $origin
            if (-not $session) {
                $hops += [pscustomobject]@{
                    Index = $index; Status = 0; Origin = $origin; SessionName = ""
                    SetCookieCount = 0; JarCookieCount = $jar.Count
                    Location = ""; Note = "READY companion session bulunamadı"
                }
                return New-ChainResult -Actor $Actor -Owner $Owner -StartUrl $StartUrl `
                    -FinalUrl $currentUrl -Status 0 -MarkerVisible $false `
                    -Verdict "MISSING_SESSION" -Hops $hops
            }

            # Seed each origin exactly once from the browser snapshot. After that,
            # Set-Cookie responses are allowed to evolve the jar just like a browser.
            if (-not $seededOrigins.ContainsKey($origin)) {
                $bridgeCookie = Get-BridgeCookieHeader -SessionName $session.name -TargetUrl $currentUrl
                Add-BridgeCookiesToJar -Jar $jar -TargetUrl $currentUrl -CookieHeader $bridgeCookie
                $seededOrigins[$origin] = $true
            }

            $request = [System.Net.Http.HttpRequestMessage]::new(
                [System.Net.Http.HttpMethod]::Get,
                $currentUrl
            )

            $response = $null
            try {
                $null = $request.Headers.TryAddWithoutValidation(
                    "User-Agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
                )
                $null = $request.Headers.TryAddWithoutValidation(
                    "Accept",
                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
                )
                $null = $request.Headers.TryAddWithoutValidation("Accept-Language", "en-US,en;q=0.9")
                $null = $request.Headers.TryAddWithoutValidation("Cache-Control", "no-cache")
                $null = $request.Headers.TryAddWithoutValidation("Pragma", "no-cache")
                $null = $request.Headers.TryAddWithoutValidation("Upgrade-Insecure-Requests", "1")
                $null = $request.Headers.TryAddWithoutValidation("Sec-Fetch-Dest", "document")
                $null = $request.Headers.TryAddWithoutValidation("Sec-Fetch-Mode", "navigate")
                $null = $request.Headers.TryAddWithoutValidation(
                    "Sec-Fetch-Site",
                    (Get-SecFetchSite -PreviousUrl $previousUrl -CurrentUrl $currentUrl)
                )
                if (-not $previousUrl) {
                    $null = $request.Headers.TryAddWithoutValidation("Sec-Fetch-User", "?1")
                }
                else {
                    $request.Headers.Referrer = [uri]$previousUrl
                }

                $response = $client.SendAsync($request).GetAwaiter().GetResult()
                $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                $status = [int]$response.StatusCode
                $location = if ($response.Headers.Location) {
                    $response.Headers.Location.ToString()
                }
                else {
                    ""
                }

                $setCookieCount = 0
                $setCookieValues = $null
                if ($response.Headers.TryGetValues("Set-Cookie", [ref]$setCookieValues)) {
                    $setCookieCount = @($setCookieValues).Count
                }

                $hops += [pscustomobject]@{
                    Index          = $index
                    Status         = $status
                    Origin         = $origin
                    SessionName    = $session.name
                    SetCookieCount = $setCookieCount
                    JarCookieCount = $jar.Count
                    Location       = $location
                    Note           = ""
                }

                if ($status -in @(301, 302, 303, 307, 308)) {
                    if (-not $location) {
                        return New-ChainResult -Actor $Actor -Owner $Owner -StartUrl $StartUrl `
                            -FinalUrl $currentUrl -Status $status -MarkerVisible $false `
                            -Verdict "REDIRECT_WITHOUT_LOCATION" -Hops $hops
                    }

                    $nextUrl = Resolve-RedirectUrl -CurrentUrl $currentUrl -Location $location
                    $nextOrigin = Get-Origin $nextUrl

                    if (-not $AllowedOrigins.ContainsKey($nextOrigin)) {
                        return New-ChainResult -Actor $Actor -Owner $Owner -StartUrl $StartUrl `
                            -FinalUrl $nextUrl -Status $status -MarkerVisible $false `
                            -Verdict "UNSUPPORTED_REDIRECT" -Hops $hops
                    }

                    $previousUrl = $currentUrl
                    $currentUrl = $nextUrl
                    continue
                }

                $markerVisible = $body.Contains($ExpectedMarker)
                $finalUri = [uri]$currentUrl
                $isSignin =
                    $finalUri.Host -eq "launchpad.37signals.com" -and
                    $finalUri.AbsolutePath -match '/signin(?:/|$)'

                $verdict = if ($status -eq 200 -and $markerVisible) {
                    "VISIBLE"
                }
                elseif ($isSignin) {
                    "AUTH_SIGNIN"
                }
                elseif ($status -in @(401, 403, 404)) {
                    "DENIED"
                }
                elseif ($status -eq 200) {
                    "200_NO_MARKER"
                }
                else {
                    "OTHER"
                }

                return New-ChainResult -Actor $Actor -Owner $Owner -StartUrl $StartUrl `
                    -FinalUrl $currentUrl -Status $status -MarkerVisible $markerVisible `
                    -Verdict $verdict -Hops $hops
            }
            finally {
                if ($response) { $response.Dispose() }
                $request.Dispose()
            }
        }

        return New-ChainResult -Actor $Actor -Owner $Owner -StartUrl $StartUrl `
            -FinalUrl $currentUrl -Status 0 -MarkerVisible $false `
            -Verdict "TOO_MANY_REDIRECTS" -Hops $hops
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Show-Result {
    param([Parameter(Mandatory)]$Result)

    $Result |
        Select-Object Actor, Owner, Status, MarkerVisible, Verdict, HopCount, FinalUrl |
        Format-Table -AutoSize

    $Result.Hops |
        Select-Object Index, Status, Origin, SessionName, SetCookieCount, JarCookieCount, Location, Note |
        Format-Table -AutoSize
}

function Save-Results {
    param([Parameter(Mandatory)]$Results)

    $outDir = Join-Path $Root "basecamp-auth-results"
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $path = Join-Path $outDir "browser-like-auth-matrix-$stamp.json"

    @($Results) |
        ConvertTo-Json -Depth 8 |
        Set-Content -Path $path -Encoding UTF8

    return $path
}

Write-Host "`n[1/5] LocalSessionBridge session haritası hazırlanıyor..." -ForegroundColor Cyan

$token = Get-BridgeToken
$sessions = Get-BridgeSessions -Token $token

$primaryA = Select-PrimarySession -Sessions $sessions -Browser $Actors.A.Browser -ProjectUrl $Actors.A.ProjectUrl
$primaryB = Select-PrimarySession -Sessions $sessions -Browser $Actors.B.Browser -ProjectUrl $Actors.B.ProjectUrl

$launchpadA = Select-OriginSession -Sessions $sessions -ClientId $primaryA.client_id -Origin "https://launchpad.37signals.com"
$launchpadB = Select-OriginSession -Sessions $sessions -ClientId $primaryB.client_id -Origin "https://launchpad.37signals.com"

if (-not $launchpadA) { throw "Chrome/A için READY Launchpad companion session yok." }
if (-not $launchpadB) { throw "Brave/B için READY Launchpad companion session yok." }

Write-Host "A / Chrome" -ForegroundColor Green
Write-Host "  Basecamp : $($primaryA.name)"
Write-Host "  Launchpad: $($launchpadA.name)"
Write-Host "B / Brave" -ForegroundColor Green
Write-Host "  Basecamp : $($primaryB.name)"
Write-Host "  Launchpad: $($launchpadB.name)"

Write-Host "`n[2/5] BASELINE A -> A (browser-like jar)..." -ForegroundColor Cyan
$baselineA = Invoke-BrowserLikeReadonlyGet `
    -Actor $Actors.A.Label -Owner "A" -StartUrl $Actors.A.ProjectUrl `
    -ExpectedMarker $Actors.A.Marker -ClientId $primaryA.client_id -Sessions $sessions
Show-Result $baselineA

Start-Sleep -Milliseconds $DelayMs

Write-Host "`n[3/5] BASELINE B -> B (browser-like jar)..." -ForegroundColor Cyan
$baselineB = Invoke-BrowserLikeReadonlyGet `
    -Actor $Actors.B.Label -Owner "B" -StartUrl $Actors.B.ProjectUrl `
    -ExpectedMarker $Actors.B.Marker -ClientId $primaryB.client_id -Sessions $sessions
Show-Result $baselineB

$results = @($baselineA, $baselineB)
$baselineGood =
    $baselineA.Status -eq 200 -and $baselineA.MarkerVisible -and
    $baselineB.Status -eq 200 -and $baselineB.MarkerVisible

if (-not $baselineGood) {
    $saved = Save-Results -Results $results
    Write-Host "`nBASELINE BAŞARISIZ. Cross-account GET çalıştırılmadı." -ForegroundColor Red
    Write-Host "Bu sürüm bridge cookie'lerini seed eder ve redirect Set-Cookie state'ini ayrı jar içinde taşır." -ForegroundColor Yellow
    Write-Host "Cookie/token değerleri loglanmadı; yalnız cookie sayıları kaydedildi." -ForegroundColor Yellow
    Write-Host "Sonuç: $saved" -ForegroundColor Cyan
    exit 2
}

Write-Host "`n[4/5] CROSS A -> B..." -ForegroundColor Yellow
Start-Sleep -Milliseconds $DelayMs
$crossAtoB = Invoke-BrowserLikeReadonlyGet `
    -Actor $Actors.A.Label -Owner "B" -StartUrl $Actors.B.ProjectUrl `
    -ExpectedMarker $Actors.B.Marker -ClientId $primaryA.client_id -Sessions $sessions
Show-Result $crossAtoB

Write-Host "`n[5/5] CROSS B -> A..." -ForegroundColor Yellow
Start-Sleep -Milliseconds $DelayMs
$crossBtoA = Invoke-BrowserLikeReadonlyGet `
    -Actor $Actors.B.Label -Owner "A" -StartUrl $Actors.A.ProjectUrl `
    -ExpectedMarker $Actors.A.Marker -ClientId $primaryB.client_id -Sessions $sessions
Show-Result $crossBtoA

$results = @($baselineA, $baselineB, $crossAtoB, $crossBtoA)
$saved = Save-Results -Results $results

$crossFinding =
    ($crossAtoB.Status -eq 200 -and $crossAtoB.MarkerVisible) -or
    ($crossBtoA.Status -eq 200 -and $crossBtoA.MarkerVisible)

Write-Host ""
if ($crossFinding) {
    Write-Host "POTANSİYEL AUTHORIZATION BYPASS: cross-account 200 + yabancı marker görüldü." -ForegroundColor Red
    Write-Host "Burada dur; mutation/POST/PATCH/DELETE yapma." -ForegroundColor Yellow
}
else {
    Write-Host "READ-ONLY PROJECT MATRIX: yabancı marker görünmedi." -ForegroundColor Green
    Write-Host "Cross AUTH_SIGNIN veya 200_NO_MARKER finding değildir." -ForegroundColor Yellow
}

Write-Host "Sonuç: $saved" -ForegroundColor Cyan
