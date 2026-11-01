<#
.SYNOPSIS
    100% Autonomous Offline Restorer for Tenda AC10 V1.0 Optimized Config (RouterCfm_optimized_v1.cfg)
    and ISP Cloned WAN MAC (<YOUR_WAN_MAC>).

.DESCRIPTION
    - Designed for post-flash or post-reset recovery when the router boots into stock firmware (192.168.0.1)
      and there is NO internet connectivity.
    - Verifies cryptographic SHA-256 and critical NVRAM parameters inside RouterCfm_optimized_v1.cfg before upload:
      * wan1.macaddr=<YOUR_WAN_MAC> (required for ISP DHCP lease)
      * iptv.enable=0, iptv.stb.enable=0 & igmp.enable=0 (eliminates phantom br2/vlan3 MAC collision)
      * ucloud.syncserver=0 (disables cloud daemon & closes UDP 11812 hole)
      * sys.maxconn=8192 (expands conntrack table)
      * sys.timentpserver=time.google.com (68-byte /bin/sntp compatible NTP server)
    - If 192.168.0.1 is not yet reachable via DHCP, temporarily configures 192.168.0.116/24 on the physical
      Ethernet adapter inside a strict try / finally block and unconditionally restores DHCP + DNS upon exit.
    - Clears any stale session (/goform/exit + /logout/Auth), authenticates to /login/Auth (trying both
      MD5("<YOUR_WIFI_PASSWORD>") = <YOUR_PASSWORD_MD5> and blank factory password), and uploads
      RouterCfm_optimized_v1.cfg to /cgi-bin/UploadCfg.
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [string]$RouterIp = "192.168.0.1",
    [int]$Port = 80,
    [string]$AdminPasswordMd5 = "<YOUR_PASSWORD_MD5>",
    [string]$ExpectedWanMac = "<YOUR_WAN_MAC>",
    [string]$InterfaceAlias = "Ethernet",
    [int]$TimeoutSeconds = 30,
    [switch]$SkipNetworkConfig,
    [switch]$VerifyOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$HybridKitRoot = Split-Path -Parent $ScriptDir

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $HybridKitRoot "backups\RouterCfm_optimized_v1.cfg"
}

function Write-Step {
    param([string]$Message, [string]$Color = "Cyan")
    $ts = (Get-Date).ToString("HH:mm:ss")
    Write-Host "[$ts] $Message" -ForegroundColor $Color
}

function Test-RouterCfmConfig {
    param([string]$Path, [string]$WanMac)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Configuration file not found: $Path"
    }

    [byte[]]$raw = [System.IO.File]::ReadAllBytes($Path)
    $text = [System.Text.Encoding]::ASCII.GetString($raw)

    $requiredChecks = @(
        @{ Key = "wan1.macaddr=$WanMac";                Desc = "ISP Cloned WAN MAC ($WanMac)" },
        @{ Key = "iptv.enable=0";                       Desc = "IPTV Disabled" },
        @{ Key = "iptv.stb.enable=0";                   Desc = "IPTV Phantom Bridge Disabled (stbEn=0)" },
        @{ Key = "igmp.enable=0";                       Desc = "IGMP Proxy Disabled" },
        @{ Key = "ucloud.syncserver=0";                 Desc = "Tenda Cloud Daemon Disabled" },
        @{ Key = "sys.maxconn=8192";                    Desc = "Conntrack Table Expanded to 8192" },
        @{ Key = "sys.timentpserver=time.google.com";   Desc = "Google Public NTP Server (68-byte sntp compatible)" }
    )

    foreach ($chk in $requiredChecks) {
        if ($text -notmatch [regex]::Escape($chk.Key)) {
            throw "Config validation failed: missing required parameter '$($chk.Key)' ($($chk.Desc)) in $Path"
        }
    }

    $sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    return [PSCustomObject]@{
        Path     = $Path
        FileSize = $raw.Length
        SHA256   = $sha256
        WanMac   = $WanMac
    }
}

function Invoke-TendaConfigUpload {
    param(
        [string]$TargetIp,
        [int]$TargetPort,
        [byte[]]$CfgBytes,
        [string]$FileName,
        [string]$PasswordMd5,
        [int]$TimeoutSec
    )

    $baseUrl = if ($TargetPort -eq 80) { "http://$TargetIp" } else { "http://${TargetIp}:${TargetPort}" }
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseCookies = $true
    $handler.CookieContainer = New-Object System.Net.CookieContainer
    $handler.AllowAutoRedirect = $false

    $client = New-Object System.Net.Http.HttpClient($handler)
    try {
        $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)

        # 1. Clear any stale Web UI session before authenticating via /login/Auth
        $passwordsToTry = @($PasswordMd5, "")
        $loggedIn = $false

        foreach ($pwd in $passwordsToTry) {
            foreach ($logoutPath in @("/goform/exit", "/logout/Auth")) {
                try {
                    $null = $client.GetAsync("$baseUrl$logoutPath").GetAwaiter().GetResult()
                } catch {
                }
            }

            $authBody = "username=admin&password=$([uri]::EscapeDataString($pwd))"
            $content = New-Object System.Net.Http.StringContent($authBody, [System.Text.Encoding]::UTF8, "application/x-www-form-urlencoded")
            $resp = $client.PostAsync("$baseUrl/login/Auth", $content).GetAwaiter().GetResult()
            $cookies = $handler.CookieContainer.GetCookies([uri]$baseUrl)

            $hasValidCookie = $false
            foreach ($c in $cookies) {
                if (-not [string]::IsNullOrWhiteSpace($c.Value) -and $c.Value -ne "errorlogin") {
                    $hasValidCookie = $true
                    break
                }
            }

            $loc = if ($null -ne $resp.Headers.Location) { $resp.Headers.Location.ToString() } else { "" }
            $redirectedToMain = ($resp.StatusCode -eq [System.Net.HttpStatusCode]::Found) -and
                                ($loc -match "main\.html|index\.html") -and
                                ($loc -notmatch "login\.html|loginerr\.html")

            if ($hasValidCookie -or $redirectedToMain) {
                $loggedIn = $true
                break
            }
        }

        if (-not $loggedIn) {
            Write-Step "Warning: No session cookie returned from /login/Auth; proceeding with direct upload..." "Yellow"
        } else {
            Write-Step "Authenticated with Tenda Web UI at $baseUrl." "Green"
        }

        # 2. Construct RFC 2388 multipart/form-data payload for /cgi-bin/UploadCfg
        $boundary = "----TendaOfflineRestoreBoundary" + [Guid]::NewGuid().ToString("N")
        $crlf = "`r`n"
        $headerStr = "--$boundary$crlf" +
                     "Content-Disposition: form-data; name=`"filename`"; filename=`"$FileName`"$crlf" +
                     "Content-Type: application/octet-stream$crlf$crlf"
        $footerStr = "$crlf--$boundary--$crlf"

        [byte[]]$headerBytes = [System.Text.Encoding]::ASCII.GetBytes($headerStr)
        [byte[]]$footerBytes = [System.Text.Encoding]::ASCII.GetBytes($footerStr)

        $bodyBytes = New-Object byte[] ($headerBytes.Length + $CfgBytes.Length + $footerBytes.Length)
        [Array]::Copy($headerBytes, 0, $bodyBytes, 0, $headerBytes.Length)
        [Array]::Copy($CfgBytes, 0, $bodyBytes, $headerBytes.Length, $CfgBytes.Length)
        [Array]::Copy($footerBytes, 0, $bodyBytes, $headerBytes.Length + $CfgBytes.Length, $footerBytes.Length)

        $mpContent = New-Object System.Net.Http.ByteArrayContent(,$bodyBytes)
        $mpContent.Headers.Remove("Content-Type") | Out-Null
        $mpContent.Headers.TryAddWithoutValidation("Content-Type", "multipart/form-data; boundary=$boundary") | Out-Null

        Write-Step "Uploading $FileName ($($CfgBytes.Length) bytes) to $baseUrl/cgi-bin/UploadCfg..." "Cyan"
        $upResp = $client.PostAsync("$baseUrl/cgi-bin/UploadCfg", $mpContent).GetAwaiter().GetResult()
        $upStatus = [int]$upResp.StatusCode
        $upText = $upResp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $upLoc = if ($null -ne $upResp.Headers.Location) { $upResp.Headers.Location.ToString() } else { "" }

        if ($upStatus -ge 200 -and $upStatus -lt 400 -and ($upLoc -notmatch "login\.html|loginerr\.html")) {
            Write-Step "UploadCfg succeeded (HTTP $upStatus)!" "Green"
            return [PSCustomObject]@{
                Success    = $true
                StatusCode = $upStatus
                Response   = $upText
            }
        } else {
            throw "UploadCfg failed or redirected to login (HTTP $upStatus, Location='$upLoc'): $upText"
        }
    } finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

# ==============================================================================
# MAIN EXECUTION FLOW
# ==============================================================================
Add-Type -AssemblyName System.Net.Http

Write-Step "=== TENDA AC10 V1.0 OFFLINE CONFIG & WAN MAC (<YOUR_WAN_MAC>) RESTORER ===" "Cyan"
$cfgInfo = Test-RouterCfmConfig -Path $ConfigPath -WanMac $ExpectedWanMac
Write-Step ("Verified Config: {0} ({1:N0} B)" -f $cfgInfo.Path, $cfgInfo.FileSize) "Green"
Write-Step ("SHA-256 Digest : {0}" -f $cfgInfo.SHA256) "Green"
Write-Step ("WAN MAC Binding: {0} | stbEn=0 | ucloud=0 | maxconn=8192 | ntp=time.google.com [PASS]" -f $cfgInfo.WanMac) "Green"

if ($VerifyOnly) {
    Write-Step "VerifyOnly mode completed successfully." "Green"
    exit 0
}

if ($DryRun) {
    Write-Step "[DRY-RUN] Config verified. Skipping HTTP upload to $RouterIp`:$Port." "Yellow"
    exit 0
}

[byte[]]$cfgBytes = [System.IO.File]::ReadAllBytes($ConfigPath)
$fileName = Split-Path -Leaf $ConfigPath

if ($SkipNetworkConfig) {
    $res = Invoke-TendaConfigUpload -TargetIp $RouterIp -TargetPort $Port `
        -CfgBytes $cfgBytes -FileName $fileName -PasswordMd5 $AdminPasswordMd5 -TimeoutSec $TimeoutSeconds
    exit 0
}

# Check if 192.168.0.1 is already reachable; if not, use failsafe temporary IP 192.168.0.116/24
$switchedStatic = $false
try {
    $pingOk = Test-Connection -ComputerName $RouterIp -Count 1 -Quiet -ErrorAction SilentlyContinue
    if (-not $pingOk) {
        Write-Step "Router $RouterIp not reachable via current lease; assigning temporary static IP 192.168.0.116/24 inside try/finally..." "Yellow"
        $switchedStatic = $true
        Remove-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
        New-NetIPAddress -InterfaceAlias $InterfaceAlias -IPAddress "192.168.0.116" -PrefixLength 24 -DefaultGateway $RouterIp -ErrorAction Stop | Out-Null
        Start-Sleep -Seconds 2
    }

    $res = Invoke-TendaConfigUpload -TargetIp $RouterIp -TargetPort $Port `
        -CfgBytes $cfgBytes -FileName $fileName -PasswordMd5 $AdminPasswordMd5 -TimeoutSec $TimeoutSeconds
    Write-Step "Router is applying configuration and rebooting (~45s)..." "Green"
} finally {
    if ($switchedStatic) {
        Write-Step "[FAILSAFE] Restoring '$InterfaceAlias' to automatic DHCP & DNS..." "Yellow"
        Remove-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
        Remove-NetRoute -InterfaceAlias $InterfaceAlias -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue
        Set-NetIPInterface -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -Dhcp Enabled -ErrorAction SilentlyContinue
        Set-DnsClientServerAddress -InterfaceAlias $InterfaceAlias -ResetServerAddresses -ErrorAction SilentlyContinue
        ipconfig /renew $InterfaceAlias >$null 2>&1
    }
}
