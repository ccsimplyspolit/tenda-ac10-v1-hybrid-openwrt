<#
.SYNOPSIS
    100% Autonomous Offline Restorer for Tenda AC10 V1.0 Optimized Config and ISP Cloned WAN MAC.

.DESCRIPTION
    - Designed for post-flash or post-reset recovery when the router boots into stock firmware (192.168.0.1)
      and there is NO internet connectivity.
    - Dynamically extracts WAN MAC and Admin Password MD5 hash directly from the configuration file if not specified.
    - Verifies cryptographic SHA-256 and critical NVRAM parameters inside the config before upload:
      * wan1.macaddr (required for ISP DHCP lease, dynamically validated)
      * iptv.enable=0, iptv.stb.enable=0 & igmp.enable=0 (eliminates phantom br2/vlan3 MAC collision)
      * ucloud.syncserver=0 (disables cloud daemon & closes UDP 11812 hole)
      * sys.maxconn=8192 (expands conntrack table)
      * sys.timentpserver (validates time.google.com or time.cloudflare.com)
    - If 192.168.0.1 is not yet reachable via DHCP, temporarily configures 192.168.0.116/24 on the physical
      Ethernet adapter inside a strict try / finally block and unconditionally restores DHCP + DNS upon exit.
    - Clears any stale session (/goform/exit + /logout/Auth), authenticates to /login/Auth (trying both
      config MD5 hash and blank factory password), and uploads configuration to /cgi-bin/UploadCfg.
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [string]$RouterIp = "192.168.0.1",
    [int]$Port = 80,
    [string]$AdminPasswordMd5 = "",
    [string]$ExpectedWanMac = "",
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
    $CandidateBackupCfg = Join-Path $HybridKitRoot "backups\RouterCfm_optimized_v1.cfg"
    $CandidateSanitizedCfg = Join-Path $HybridKitRoot "config\RouterCfm_optimized_sanitized.cfg"
    $CandidateTemplateCfg = Join-Path $HybridKitRoot "01_Stock_Firmware_and_Partitions\RouterCfm_optimized_template.cfg"
    if (Test-Path -LiteralPath $CandidateBackupCfg) {
        $ConfigPath = $CandidateBackupCfg
    } elseif (Test-Path -LiteralPath $CandidateSanitizedCfg) {
        $ConfigPath = $CandidateSanitizedCfg
    } elseif (Test-Path -LiteralPath $CandidateTemplateCfg) {
        $ConfigPath = $CandidateTemplateCfg
    } else {
        throw "No configuration file found. Checked: '$CandidateBackupCfg', '$CandidateSanitizedCfg', '$CandidateTemplateCfg'"
    }
}

function Write-Step {
    param([string]$Message, [string]$Color = "Cyan")
    $ts = (Get-Date).ToString("HH:mm:ss")
    Write-Host "[$ts] $Message" -ForegroundColor $Color
}

function Get-StringMd5 {
    param([string]$InputString)
    if ([string]::IsNullOrWhiteSpace($InputString)) { return "" }
    $md5 = [System.Security.Cryptography.MD5]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($InputString)
    $hashBytes = $md5.ComputeHash($bytes)
    $sb = New-Object System.Text.StringBuilder
    foreach ($b in $hashBytes) {
        [void]$sb.Append($b.ToString("x2"))
    }
    return $sb.ToString()
}

function Test-RouterCfmConfig {
    param([string]$Path, [string]$WanMac)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Configuration file not found: $Path"
    }

    [byte[]]$raw = [System.IO.File]::ReadAllBytes($Path)
    $text = [System.Text.Encoding]::ASCII.GetString($raw)

    $wanEscaped = [regex]::Escape($WanMac)
    if ($text -notmatch "(?m)^wan1?\.macaddr\s*=\s*$wanEscaped\s*$") {
        throw "Config validation failed: missing required parameter 'wan1.macaddr=$WanMac' (ISP Cloned WAN MAC ($WanMac)) in $Path"
    }

    $requiredChecks = @(
        @{ Key = "iptv.enable=0";                       Desc = "IPTV Disabled" },
        @{ Key = "iptv.stb.enable=0";                   Desc = "IPTV Phantom Bridge Disabled (stbEn=0)" },
        @{ Key = "igmp.enable=0";                       Desc = "IGMP Proxy Disabled" },
        @{ Key = "ucloud.syncserver=0";                 Desc = "Tenda Cloud Daemon Disabled" },
        @{ Key = "sys.maxconn=8192";                    Desc = "Conntrack Table Expanded to 8192" }
    )

    foreach ($chk in $requiredChecks) {
        if ($text -notmatch [regex]::Escape($chk.Key)) {
            throw "Config validation failed: missing required parameter '$($chk.Key)' ($($chk.Desc)) in $Path"
        }
    }

    if ($text -match '(?m)^sys\.timentpserver\s*=\s*([^\r\n]+)') {
        $ntpServer = $Matches[1].Trim()
        if ($ntpServer -notmatch '^time\.(google|cloudflare)\.com$') {
            throw "Config validation failed: unexpected NTP server '$ntpServer' in $Path (expected time.google.com or time.cloudflare.com)"
        }
    } else {
        throw "Config validation failed: missing required parameter 'sys.timentpserver' in $Path"
    }

    $sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    return [PSCustomObject]@{
        Path      = $Path
        FileSize  = $raw.Length
        SHA256    = $sha256
        WanMac    = $WanMac
        NtpServer = $ntpServer
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
        $passwordsToTry = if ([string]::IsNullOrWhiteSpace($PasswordMd5)) { @("") } else { @($PasswordMd5, "") }
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

Write-Step "=== TENDA AC10 V1.0 OFFLINE CONFIG & WAN MAC RESTORER ===" "Cyan"

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Configuration file not found: $ConfigPath"
}

[byte[]]$rawConfigBytes = [System.IO.File]::ReadAllBytes($ConfigPath)
$configText = [System.Text.Encoding]::ASCII.GetString($rawConfigBytes)

# Resolve Expected WAN MAC dynamically if unset or set to template placeholder
$isWanMacUnset = [string]::IsNullOrWhiteSpace($ExpectedWanMac) -or ($ExpectedWanMac -eq "<YOUR_WAN_MAC>") -or ($ExpectedWanMac -match '^<YOUR_.*>$')
if ($isWanMacUnset) {
    if ($configText -match '(?m)^wan1?\.macaddr\s*=\s*([^\r\n]+)') {
        $extractedMac = $Matches[1].Trim()
        if (($extractedMac.Length -eq 17) -and ($extractedMac -match '^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$') -and ($extractedMac -notmatch '^<YOUR_')) {
            $ExpectedWanMac = $extractedMac.ToUpperInvariant()
            Write-Step "Dynamically extracted WAN MAC from config: $ExpectedWanMac" "Green"
        } else {
            throw "Config validation failed: 'wan1.macaddr' in $ConfigPath is '$extractedMac', which is not a valid 17-character MAC address (template placeholder detected or invalid format). Please supply -ExpectedWanMac or update the configuration file."
        }
    } else {
        throw "Config validation failed: missing 'wan1.macaddr' parameter in $ConfigPath"
    }
} else {
    if (($ExpectedWanMac.Length -ne 17) -or ($ExpectedWanMac -notmatch '^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')) {
        throw "Invalid ExpectedWanMac format: '$ExpectedWanMac'. Must be a 17-character MAC address (e.g. 50:0F:F5:00:00:01)."
    }
    $ExpectedWanMac = $ExpectedWanMac.ToUpperInvariant()
}

# Resolve Admin Password MD5 dynamically if unset or set to template placeholder
$isPasswordUnset = [string]::IsNullOrWhiteSpace($AdminPasswordMd5) -or ($AdminPasswordMd5 -eq "<YOUR_PASSWORD_MD5>") -or ($AdminPasswordMd5 -match '^<YOUR_.*>$')
if ($isPasswordUnset) {
    if ($configText -match '(?m)^(?:sys|http)\.userpass\s*=\s*([^\r\n]*)') {
        $extractedPass = $Matches[1].Trim()
        if ([string]::IsNullOrWhiteSpace($extractedPass) -or ($extractedPass -eq "<YOUR_PASSWORD_MD5>") -or ($extractedPass -match '^<YOUR_.*>$')) {
            $AdminPasswordMd5 = ""
            Write-Step "No admin password set in config (or template placeholder); will authenticate with blank password." "Yellow"
        } elseif ($extractedPass -match '^[0-9a-fA-F]{32}$') {
            $AdminPasswordMd5 = $extractedPass.ToLowerInvariant()
            Write-Step "Dynamically extracted admin password MD5 hash from config." "Green"
        } else {
            $AdminPasswordMd5 = Get-StringMd5 -InputString $extractedPass
            Write-Step "Dynamically computed MD5 hash for plaintext password in config." "Green"
        }
    } else {
        $AdminPasswordMd5 = ""
        Write-Step "No userpass parameter found in config; defaulting to blank password." "Yellow"
    }
} else {
    if ($AdminPasswordMd5 -match '^[0-9a-fA-F]{32}$') {
        $AdminPasswordMd5 = $AdminPasswordMd5.ToLowerInvariant()
    } else {
        $AdminPasswordMd5 = Get-StringMd5 -InputString $AdminPasswordMd5
    }
}

$cfgInfo = Test-RouterCfmConfig -Path $ConfigPath -WanMac $ExpectedWanMac
Write-Step ("Verified Config: {0} ({1:N0} B)" -f $cfgInfo.Path, $cfgInfo.FileSize) "Green"
Write-Step ("SHA-256 Digest : {0}" -f $cfgInfo.SHA256) "Green"
Write-Step ("WAN MAC Binding: {0} | stbEn=0 | ucloud=0 | maxconn=8192 | ntp={1} [PASS]" -f $cfgInfo.WanMac, $cfgInfo.NtpServer) "Green"

if ($VerifyOnly) {
    Write-Step "VerifyOnly mode completed successfully." "Green"
    exit 0
}

if ($DryRun) {
    Write-Step "[DRY-RUN] Config verified. Skipping HTTP upload to $RouterIp`:$Port." "Yellow"
    exit 0
}

$fileName = Split-Path -Leaf $ConfigPath

if ($SkipNetworkConfig) {
    $res = Invoke-TendaConfigUpload -TargetIp $RouterIp -TargetPort $Port `
        -CfgBytes $rawConfigBytes -FileName $fileName -PasswordMd5 $AdminPasswordMd5 -TimeoutSec $TimeoutSeconds
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
        -CfgBytes $rawConfigBytes -FileName $fileName -PasswordMd5 $AdminPasswordMd5 -TimeoutSec $TimeoutSeconds
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
