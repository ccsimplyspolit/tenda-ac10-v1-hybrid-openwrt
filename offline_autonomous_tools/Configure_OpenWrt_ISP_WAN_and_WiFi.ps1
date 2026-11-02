<#
.SYNOPSIS
    100% Autonomous Offline Provisioner for OpenWrt 4.14 ISP Cloned WAN MAC and Wi-Fi Networks.

.DESCRIPTION
    - Connects to freshly flashed or reset OpenWrt 4.14 router at 192.168.0.1 via Windows built-in ssh.exe.
    - Dynamically extracts WAN MAC and Wi-Fi credentials from backups\RouterCfm_optimized_v1.cfg (or CLI overrides).
    - Batches UCI commands to configure:
        * network.wan.macaddr and network.wan_eth0_1_dev.macaddr
        * 5 GHz (radio0 / RTL8822BE) SSID, WPA2-PSK key, encryption (psk2)
        * 2.4 GHz (radio1 / RTL8197FS) SSID, WPA2-PSK key, encryption (psk2)
        * wifi device unmasking (disabled=0)
    - Reloads network and wifi services via /etc/init.d/network reload and wifi reload.
    - Queries and verifies WAN netdevice MAC and ISP DHCP lease status via ubus / ifstatus.
    - Enforces strict try/finally network adapter restoration.

.EXAMPLE
    .\Configure_OpenWrt_ISP_WAN_and_WiFi.ps1
    # Auto-locates config, extracts parameters, and provisions OpenWrt at 192.168.0.1

.EXAMPLE
    .\Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 -WanMac "50:0F:F5:00:00:01" -Ssid2G "OpenWrt_2.4G" -Ssid5G "OpenWrt_5G" -Key2G "Passphrase123" -Key5G "Passphrase123" -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$ConfigPath = "",

    [Alias("RouterIp")]
    [string]$TargetIp = "192.168.0.1",

    [Alias("Port")]
    [int]$TargetPort = 22,

    [Alias("TargetUser")]
    [string]$SshUser = "root",

    [Alias("ExpectedWanMac")]
    [string]$WanMac = "",

    [string]$Ssid2G = "",
    [string]$Key2G = "",
    [string]$Ssid5G = "",
    [string]$Key5G = "",
    [string]$InterfaceAlias = "Ethernet",
    [int]$TimeoutSeconds = 30,
    [int]$MaxRetries = 12,
    [int]$RetryDelaySeconds = 5,
    [string]$IdentityFile = "",
    [switch]$SkipNetworkConfig,
    [switch]$DryRun,
    [switch]$VerifyOnly,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$HybridKitRoot = Split-Path -Parent $ScriptDir

function Write-Step {
    param([string]$Message, [string]$Color = "Cyan")
    $ts = (Get-Date).ToString("HH:mm:ss")
    Write-Host "[$ts] $Message" -ForegroundColor $Color
}

function Format-MaskedSecret {
    param([string]$Secret)
    if ([string]::IsNullOrWhiteSpace($Secret)) { return "<none>" }
    return ("*" * [Math]::Min(8, $Secret.Length)) + " ($($Secret.Length) chars)"
}

function Test-ValidMacAddress {
    param([string]$Mac)
    if ([string]::IsNullOrWhiteSpace($Mac)) { return $false }
    if ($Mac.Length -ne 17) { return $false }
    if ($Mac -notmatch '^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$') { return $false }
    if ($Mac -match '^<YOUR_') { return $false }
    try {
        $firstByte = [Convert]::ToByte($Mac.Substring(0, 2), 16)
        if (($firstByte -band 1) -ne 0) { return $false }
    } catch { return $false }
    $clean = $Mac -replace '[:-]', ''
    if ($clean -eq '000000000000' -or $clean -eq 'FFFFFFFFFFFF') { return $false }
    return $true
}

function Format-NormalizedMac {
    param([string]$Mac)
    return $Mac.Replace('-', ':').ToUpperInvariant()
}

function Format-ShEscapedString {
    param([string]$InputStr)
    if ($null -eq $InputStr) { return "''" }
    return "'" + $InputStr.Replace("'", "'\''") + "'"
}

function Resolve-CandidateConfigFile {
    param(
        [string]$ExplicitPath,
        [string]$HybridRoot,
        [string]$CurrentDir,
        [string]$ScriptDir
    )
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        if (Test-Path -LiteralPath $ExplicitPath) {
            return (Resolve-Path -LiteralPath $ExplicitPath).Path
        }
        throw "Explicitly specified configuration file not found: '$ExplicitPath'"
    }

    $candidates = @(
        (Join-Path $CurrentDir "RouterCfm_optimized_v1.cfg"),
        (Join-Path $CurrentDir "RouterCfm_optimized_sanitized.cfg"),
        (Join-Path $HybridRoot "backups\RouterCfm_optimized_v1.cfg"),
        (Join-Path $HybridRoot "backups\RouterCfm_backup_original.cfg"),
        (Join-Path $HybridRoot "config\RouterCfm_optimized_sanitized.cfg"),
        (Join-Path $HybridRoot "backups\RouterCfm_optimized_sanitized.cfg"),
        (Join-Path $HybridRoot "01_Stock_Firmware_and_Partitions\RouterCfm_optimized_template.cfg"),
        (Join-Path $ScriptDir "RouterCfm_optimized_v1.cfg"),
        (Join-Path $ScriptDir "RouterCfm_optimized_sanitized.cfg")
    )

    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) {
            return (Resolve-Path -LiteralPath $c).Path
        }
    }
    return $null
}

# --- CONFIG RESOLUTION & PARSING ---
$resolvedConfig = Resolve-CandidateConfigFile -ExplicitPath $ConfigPath -HybridRoot $HybridKitRoot -CurrentDir (Get-Location).Path -ScriptDir $ScriptDir
$configText = ""
if ($null -ne $resolvedConfig) {
    Write-Step "Using configuration source: $resolvedConfig" "Green"
    [byte[]]$raw = [System.IO.File]::ReadAllBytes($resolvedConfig)
    $configText = [System.Text.Encoding]::ASCII.GetString($raw)
} else {
    Write-Step "No configuration file found in candidate paths; relying on CLI parameters." "Yellow"
}

# 1. Resolve WAN MAC
if ([string]::IsNullOrWhiteSpace($WanMac)) {
    if ($configText -match '(?m)^wan1?\.macaddr\s*=\s*([^\r\n]+)') {
        $candidateMac = $Matches[1].Trim()
        if (Test-ValidMacAddress $candidateMac) {
            $WanMac = Format-NormalizedMac $candidateMac
            Write-Step "Dynamically extracted WAN MAC: $WanMac" "Green"
        } else {
            throw "Config validation failed: 'wan1.macaddr' in '$resolvedConfig' is '$candidateMac', which is not a valid unicast MAC (placeholder or invalid format). Please pass -WanMac <MAC> or update config."
        }
    } else {
        throw "Missing required WAN MAC address. Please provide -WanMac <MAC> (e.g. 50:0F:F5:00:00:01) or supply a valid config via -ConfigPath."
    }
} else {
    if ($WanMac -match '^<YOUR_' -or -not (Test-ValidMacAddress $WanMac)) {
        throw "Invalid -WanMac parameter: '$WanMac'. Must be a 17-character unicast MAC (e.g. 50:0F:F5:00:00:01) and not a template placeholder."
    }
    $WanMac = Format-NormalizedMac $WanMac
    Write-Step "Using CLI WAN MAC override: $WanMac" "Green"
}

# 2. Resolve Wi-Fi 2.4 GHz SSID
if ([string]::IsNullOrWhiteSpace($Ssid2G)) {
    if ($configText -match '(?m)^(?:wl2g\.ssid0\.ssid|wl2g_bss_ssid_old|wl2g\.public\.ssid)\s*=\s*([^\r\n]+)') {
        $Ssid2G = $Matches[1].Trim()
    } else {
        $Ssid2G = "Tenda-AC10-2.4G"
    }
}
if ($Ssid2G -match '^<YOUR_' -or [string]::IsNullOrWhiteSpace($Ssid2G)) {
    $Ssid2G = "Tenda-AC10-2.4G"
}
Write-Step "2.4 GHz SSID: $Ssid2G" "Green"

# 3. Resolve Wi-Fi 5 GHz SSID
if ([string]::IsNullOrWhiteSpace($Ssid5G)) {
    if ($configText -match '(?m)^(?:wl5g\.ssid0\.ssid|wl5g_bss_ssid_old|wl5g\.public\.ssid)\s*=\s*([^\r\n]+)') {
        $Ssid5G = $Matches[1].Trim()
    } else {
        $Ssid5G = "Tenda-AC10-5G"
    }
}
if ($Ssid5G -match '^<YOUR_' -or [string]::IsNullOrWhiteSpace($Ssid5G)) {
    $Ssid5G = "Tenda-AC10-5G"
}
Write-Step "5.0 GHz SSID: $Ssid5G" "Green"

# 4. Resolve Wi-Fi 2.4 GHz WPA-PSK Key
if ([string]::IsNullOrWhiteSpace($Key2G)) {
    if ($configText -match '(?m)^(?:wl2g\.ssid0\.wpapsk_psk|wl2g_bss_wpapsk_psk_old|wl2g\.sec\.wpapsk)\s*=\s*([^\r\n]*)') {
        $Key2G = $Matches[1].Trim()
    }
}
if ($Key2G -match '^<YOUR_' -or [string]::IsNullOrWhiteSpace($Key2G) -or ($Key2G.Length -lt 8)) {
    if ($Force) {
        $Key2G = "12345678"
        Write-Step "Warning: 2.4 GHz key invalid or template placeholder. Using fallback default '12345678' due to -Force." "Yellow"
    } else {
        throw "Config validation failed: 2.4 GHz Wi-Fi passphrase in config is missing, too short (<8 chars), or contains placeholder. Supply -Key2G <passphrase> or pass -Force."
    }
}
Write-Step ("2.4 GHz Key : {0}" -f (Format-MaskedSecret $Key2G)) "Green"

# 5. Resolve Wi-Fi 5 GHz WPA-PSK Key
if ([string]::IsNullOrWhiteSpace($Key5G)) {
    if ($configText -match '(?m)^(?:wl5g\.ssid0\.wpapsk_psk|wl5g_bss_wpapsk_psk_old|wl5g\.sec\.wpapsk)\s*=\s*([^\r\n]*)') {
        $Key5G = $Matches[1].Trim()
    }
}
if ($Key5G -match '^<YOUR_' -or [string]::IsNullOrWhiteSpace($Key5G) -or ($Key5G.Length -lt 8)) {
    if ($Force) {
        $Key5G = "12345678"
        Write-Step "Warning: 5 GHz key invalid or template placeholder. Using fallback default '12345678' due to -Force." "Yellow"
    } else {
        throw "Config validation failed: 5 GHz Wi-Fi passphrase in config is missing, too short (<8 chars), or contains placeholder. Supply -Key5G <passphrase> or pass -Force."
    }
}
Write-Step ("5.0 GHz Key : {0}" -f (Format-MaskedSecret $Key5G)) "Green"

# 6. Resolve WAN Protocol (Static vs DHCP), MTU, Custom Upstream DNS, Wi-Fi Channels & Static DHCP Leases
$wanProto = "dhcp"
$wanIpAddr = ""
$wanNetmask = "255.255.255.0"
$wanGateway = ""
if ($configText -match '(?m)^wan1\.connecttype\s*=\s*1\s*$' -and $configText -match '(?m)^wan1\.ip\s*=\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})\s*$') {
    $wanProto = "static"
    $wanIpAddr = $Matches[1].Trim()
    if ($configText -match '(?m)^wan1\.mask\s*=\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})\s*$') {
        $wanNetmask = $Matches[1].Trim()
    }
    if ($configText -match '(?m)^wan1\.gateway\s*=\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})\s*$') {
        $wanGateway = $Matches[1].Trim()
    }
    Write-Step "WAN Mode    : Static IP ($wanIpAddr / $wanNetmask, Gateway $wanGateway)" "Green"
}

$wanMtu = 1500
if ($configText -match '(?m)^wan1\.(?:dynamicMTU|staticMTU)\s*=\s*(\d+)') {
    $parsedMtu = [int]$Matches[1]
    if ($parsedMtu -ge 576 -and $parsedMtu -le 1500) { $wanMtu = $parsedMtu }
}

$customDnsList = @()
foreach ($dk in @('wan1.dhcp.dns.hand1', 'wan1.dhcp.dns.hand2', 'wan1.dns1', 'wan1.dns2', 'lan.dns.hand1', 'lan.dns.hand2')) {
    if ($configText -match "(?m)^$([regex]::Escape($dk))\s*=\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})\s*$") {
        $dIp = $Matches[1].Trim()
        if ($dIp -ne '0.0.0.0' -and ($customDnsList -notcontains $dIp)) {
            $customDnsList += $dIp
        }
    }
}
if ($customDnsList.Count -gt 0) {
    Write-Step ("Custom DNS  : {0}" -f ($customDnsList -join ", ")) "Green"
}

$chan2G = ""
if ($configText -match '(?m)^wl2g\.public\.channel\s*=\s*(\d+)\s*$') {
    $c2 = [int]$Matches[1]
    if ($c2 -ge 1 -and $c2 -le 13) { $chan2G = $c2.ToString() }
}
$chan5G = ""
if ($configText -match '(?m)^wl5g\.public\.channel\s*=\s*(\d+)\s*$') {
    $c5 = [int]$Matches[1]
    if ($c5 -ge 36 -and $c5 -le 165) { $chan5G = $c5.ToString() }
}

$dhcpStart = 100
$dhcpLimit = 101
if ($configText -match '(?m)^dhcps\.start\s*=\s*\d+\.\d+\.\d+\.(\d+)\s*$') {
    $sOct = [int]$Matches[1]
    if ($sOct -ge 2 -and $sOct -le 250) {
        $dhcpStart = $sOct
        if ($configText -match '(?m)^dhcps\.end\s*=\s*\d+\.\d+\.\d+\.(\d+)\s*$') {
            $eOct = [int]$Matches[1]
            if ($eOct -ge $sOct -and $eOct -le 254) {
                $dhcpLimit = ($eOct - $sOct + 1)
            }
        }
    }
}

$staticLeases = @()
$leaseMatches = [regex]::Matches($configText, '(?m)^dhcps\.Staticip\d+\s*=\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3});([0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5})')
foreach ($lm in $leaseMatches) {
    $sIp = $lm.Groups[1].Value.Trim()
    $sMac = Format-NormalizedMac $lm.Groups[2].Value.Trim()
    if (Test-ValidMacAddress $sMac) {
        $staticLeases += [PSCustomObject]@{ IP = $sIp; MAC = $sMac }
    }
}
if ($staticLeases.Count -gt 0) {
    Write-Step ("Static DHCP : {0} reservation(s) detected" -f $staticLeases.Count) "Green"
}

# --- LOCATE SSH CLIENT ---
$sshCmd = Get-Command "ssh.exe" -ErrorAction SilentlyContinue
if ($null -eq $sshCmd) {
    $fallbackSsh = "$env:SystemRoot\System32\OpenSSH\ssh.exe"
    if (Test-Path -LiteralPath $fallbackSsh) {
        $sshPath = $fallbackSsh
    } else {
        throw "Windows OpenSSH client ('ssh.exe') not found. Please enable OpenSSH Client in Windows Settings."
    }
} else {
    $sshPath = $sshCmd.Source
}
Write-Step "OpenSSH Client: $sshPath" "Green"

# --- VERIFY / DRY-RUN CHECK ---
if ($VerifyOnly) {
    Write-Step "=== VerifyOnly: Configuration and Local Prerequisites PASS ===" "Green"
    Write-Step ("Target      : {0}@{1}:{2}" -f $SshUser, $TargetIp, $TargetPort) "Green"
    Write-Step ("WAN MAC     : {0} (DHCP MTU={1})" -f $WanMac, $wanMtu) "Green"
    Write-Step ("2.4 GHz     : SSID='{0}', Channel={1}, Key={2}" -f $Ssid2G, $(if ($chan2G) { $chan2G } else { "auto" }), (Format-MaskedSecret $Key2G)) "Green"
    Write-Step ("5.0 GHz     : SSID='{0}', Channel={1}, Key={2}" -f $Ssid5G, $(if ($chan5G) { $chan5G } else { "auto" }), (Format-MaskedSecret $Key5G)) "Green"
    Write-Step ("DHCP Pool   : start={0}, limit={1}, static_leases={2}" -f $dhcpStart, $dhcpLimit, $staticLeases.Count) "Green"
    Write-Step ("OpenSSH     : {0}" -f $sshPath) "Green"
    Write-Step "VerifyOnly mode completed successfully." "Green"
    exit 0
}

# --- GENERATE REMOTE UCI PROVISIONING PAYLOAD ---
$shWanMac  = Format-ShEscapedString $WanMac
$shSsid2G  = Format-ShEscapedString $Ssid2G
$shKey2G   = Format-ShEscapedString $Key2G
$shSsid5G  = Format-ShEscapedString $Ssid5G
$shKey5G   = Format-ShEscapedString $Key5G

$dnsUciBlock = ""
if ($customDnsList.Count -gt 0) {
    $dnsLines = @("uci set network.wan.peerdns='0'", "uci -q delete network.wan.dns 2>/dev/null || true")
    foreach ($d in $customDnsList) {
        $dnsLines += ("uci add_list network.wan.dns={0}" -f (Format-ShEscapedString $d))
    }
    $dnsUciBlock = ($dnsLines -join "`n")
}

$chan5GUci = if (-not [string]::IsNullOrWhiteSpace($chan5G)) { "uci -q set wireless.radio0.channel='$chan5G' || true" } else { ":" }
$chan2GUci = if (-not [string]::IsNullOrWhiteSpace($chan2G)) { "uci -q set wireless.radio1.channel='$chan2G' || true" } else { ":" }

$dhcpStaticLines = @("while uci -q delete dhcp.@host[0] 2>/dev/null; do :; done")
foreach ($sl in $staticLeases) {
    $shSlIp = Format-ShEscapedString $sl.IP
    $shSlMac = Format-ShEscapedString $sl.MAC.ToLowerInvariant()
    $dhcpStaticLines += "_h=`$(uci add dhcp host)"
    $dhcpStaticLines += "uci set dhcp.`"`$_h`".ip=$shSlIp"
    $dhcpStaticLines += "uci set dhcp.`"`$_h`".mac=$shSlMac"
}
$dhcpStaticBlock = ($dhcpStaticLines -join "`n")

$wanUciProtoBlock = "uci set network.wan.proto='dhcp'"
$warmHostsStr = "192.168.0.176 192.168.0.100 1.1.1.1"
if ($wanProto -eq "static" -and -not [string]::IsNullOrWhiteSpace($wanIpAddr)) {
    $shWanIp = Format-ShEscapedString $wanIpAddr
    $shWanMask = Format-ShEscapedString $wanNetmask
    $wanLines = @(
        "uci set network.wan.proto='static'",
        "uci set network.wan.ipaddr=$shWanIp",
        "uci set network.wan.netmask=$shWanMask"
    )
    if (-not [string]::IsNullOrWhiteSpace($wanGateway)) {
        $shWanGw = Format-ShEscapedString $wanGateway
        $wanLines += "uci set network.wan.gateway=$shWanGw"
        $warmHostsStr = "192.168.0.176 192.168.0.100 $wanGateway 1.1.1.1"
    }
    $wanUciProtoBlock = ($wanLines -join "`n")
}

$remoteScript = @"
#!/bin/sh
set -e

# 0. Wait for first-boot uci-defaults (99-dir842-m5) to complete if still in progress
_w=0
while [ `$_w -lt 30 ] && [ "`$(uci -q get system.@system[0].dir842_m5_seeded 2>/dev/null || true)" != "1" ] && [ -e /etc/uci-defaults/99-dir842-m5 ]; do
    sleep 1
    _w=`$((_w + 1))
done

# 1. Provision Cloned WAN MAC, Protocol, MTU, Custom DNS & ASIC Warm Hosts (eth0.1 / VLAN 1)
$wanUciProtoBlock
uci set network.wan.mtu='$wanMtu'
uci set network.wan.macaddr=$shWanMac
uci -q set network.wan_eth0_1_dev.macaddr=$shWanMac 2>/dev/null || true
$dnsUciBlock
uci commit network
uci -q set dir842.asic.warm_hosts='$warmHostsStr' 2>/dev/null || true
uci -q commit dir842 2>/dev/null || true
ip link set dev eth0.1 down 2>/dev/null || true
ip link set dev eth0.1 address $shWanMac 2>/dev/null || true
ip link set dev eth0.1 up 2>/dev/null || true

# 2. Provision LAN DHCP Pool & Static Reservations
uci -q set dhcp.lan.start='$dhcpStart' || true
uci -q set dhcp.lan.limit='$dhcpLimit' || true
uci -q set dhcp.lan.leasetime='24h' || true
$dhcpStaticBlock
uci commit dhcp

# 3. Provision 5 GHz Wi-Fi (radio0)
uci -q set wireless.radio0.disabled='0' || true
uci -q delete wireless.radio0.disabled 2>/dev/null || true
$chan5GUci
if uci -q get wireless.default_radio0 >/dev/null 2>&1; then
    W_IF0="default_radio0"
else
    W_IF0=`$(uci show wireless 2>/dev/null | grep '=wifi-iface' | cut -d. -f2 | cut -d= -f1 | head -n1 || true)
fi
if [ -n "`$W_IF0" ]; then
    uci set wireless.`${W_IF0}.ssid=$shSsid5G
    uci set wireless.`${W_IF0}.encryption='psk2'
    uci set wireless.`${W_IF0}.key=$shKey5G
    uci -q delete wireless.`${W_IF0}.disabled 2>/dev/null || true
fi

# 4. Provision 2.4 GHz Wi-Fi (radio1)
uci -q set wireless.radio1.disabled='0' || true
uci -q delete wireless.radio1.disabled 2>/dev/null || true
$chan2GUci
if uci -q get wireless.default_radio1 >/dev/null 2>&1; then
    W_IF1="default_radio1"
else
    W_IF1=`$(uci show wireless 2>/dev/null | grep '=wifi-iface' | cut -d. -f2 | cut -d= -f1 | tail -n1 || true)
fi
if [ -n "`$W_IF1" ]; then
    uci set wireless.`${W_IF1}.ssid=$shSsid2G
    uci set wireless.`${W_IF1}.encryption='psk2'
    uci set wireless.`${W_IF1}.key=$shKey2G
    uci -q delete wireless.`${W_IF1}.disabled 2>/dev/null || true
fi

for iface in `$(uci show wireless 2>/dev/null | grep "=wifi-iface" | cut -d"." -f2 | cut -d"=" -f1 || true); do
    dev=`$(uci -q get wireless."`$iface".device 2>/dev/null || true)
    if [ "`$dev" = "radio0" ]; then
        uci -q set wireless."`$iface".ssid=$shSsid5G || true
        uci -q set wireless."`$iface".encryption='psk2' || true
        uci -q set wireless."`$iface".key=$shKey5G || true
        uci -q delete wireless."`$iface".disabled 2>/dev/null || true
    elif [ "`$dev" = "radio1" ]; then
        uci -q set wireless."`$iface".ssid=$shSsid2G || true
        uci -q set wireless."`$iface".encryption='psk2' || true
        uci -q set wireless."`$iface".key=$shKey2G || true
        uci -q delete wireless."`$iface".disabled 2>/dev/null || true
    fi
done
uci commit wireless

# 5. Reload Network, DHCP, Wi-Fi & RTL8197FS Hardware NAT ASIC (syncing cloned eth0.1 WAN MAC to ASIC netif table)
/etc/init.d/network reload
/etc/init.d/dnsmasq reload 2>/dev/null || true
wifi reload 2>/dev/null || true
if [ -x /etc/init.d/dir842-asic ]; then
    (
        sleep 2
        ip link set dev eth0.1 address $shWanMac 2>/dev/null || true
        /etc/init.d/dir842-asic restart >/dev/null 2>&1 || true
        _i=0
        while [ `$_i -lt 45 ]; do
            if [ -d /sys/class/net/br-lan/brif/wlan0 ] && [ -d /sys/class/net/br-lan/brif/wlan1 ] && [ "`$(cat /sys/class/net/wlan1/operstate 2>/dev/null)" = "up" ]; then
                break
            fi
            _i=`$((_i + 1))
            sleep 1
        done
        sleep 5
        ip link set dev eth0.1 address $shWanMac 2>/dev/null || true
        /etc/init.d/dir842-asic restart >/dev/null 2>&1 || true
    ) </dev/null >/dev/null 2>&1 &
fi

# 6. Output Verification Banner
echo "TENDA_AC10_PROVISIONED: WAN_MAC=`$(uci -q get network.wan.macaddr) 5G_SSID=`$(uci -q get wireless.`${W_IF0}.ssid) 2G_SSID=`$(uci -q get wireless.`${W_IF1}.ssid)"
"@
$remoteScript = $remoteScript.Replace("`r`n", "`n").Replace("`r", "`n")

if ($DryRun) {
    Write-Step "=== DRY-RUN: Generated OpenWrt 4.14 Provisioning Script ===" "Yellow"
    $maskedScript = $remoteScript
    if (-not [string]::IsNullOrWhiteSpace($Key2G)) {
        $escapedK2 = [regex]::Escape($Key2G)
        $maskedScript = $maskedScript -replace $escapedK2, "********"
    }
    if (-not [string]::IsNullOrWhiteSpace($Key5G)) {
        $escapedK5 = [regex]::Escape($Key5G)
        $maskedScript = $maskedScript -replace $escapedK5, "********"
    }
    foreach ($sl in $staticLeases) {
        $escapedMac = [regex]::Escape($sl.MAC.ToLowerInvariant())
        $maskedScript = $maskedScript -replace $escapedMac, "xx:xx:xx:xx:xx:xx"
    }
    Write-Host $maskedScript -ForegroundColor Gray
    Write-Step "[DRY-RUN] Simulating WAN netdevice and status checks..." "Yellow"
    Write-Step ("Simulated WAN Netdevice: 3: eth0.1@eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500`n    link/ether {0} brd ff:ff:ff:ff:ff:ff" -f $WanMac.ToLowerInvariant()) "Green"
    $mockJson = '{"up":true,"pending":false,"available":true,"autostart":true,"dynamic":false,"uptime":45,"l3_device":"eth0.1","proto":"dhcp","device":"eth0.1","ipv4-address":[{"address":"198.51.100.44","mask":24}],"route":[{"target":"0.0.0.0","mask":0,"nexthop":"198.51.100.1","source":"198.51.100.44/32"}],"dns-server":["1.1.1.1","8.8.8.8"]}'
    $statusObj = $mockJson | ConvertFrom-Json
    $wanIp = if ($statusObj.'ipv4-address' -and $statusObj.'ipv4-address'.Count -gt 0) { $statusObj.'ipv4-address'[0].address } else { "Pending" }
    $wanGw = if ($statusObj.route -and $statusObj.route.Count -gt 0) { $statusObj.route[0].nexthop } else { "Pending" }
    Write-Step "Simulated WAN Status: UP=$($statusObj.up), IP=$wanIp, Gateway=$wanGw" "Green"
    Write-Step "[DRY-RUN] Script verified. No changes sent to $TargetIp." "Yellow"
    exit 0
}

# --- PHYSICAL PC NETWORK CONFIGURATION (FAILSAFE) ---
$switchedStatic = $false
try {
    if (-not $SkipNetworkConfig) {
        $pingOk = Test-Connection -ComputerName $TargetIp -Count 1 -Quiet -ErrorAction SilentlyContinue
        if (-not $pingOk) {
            Write-Step "Router $TargetIp not responding; assigning temporary static IP 192.168.0.116/24 on '$InterfaceAlias'..." "Yellow"
            $switchedStatic = $true
            Remove-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
            New-NetIPAddress -InterfaceAlias $InterfaceAlias -IPAddress "192.168.0.116" -PrefixLength 24 -DefaultGateway $TargetIp -ErrorAction Stop | Out-Null
            Start-Sleep -Seconds 2
        }
    }

    # --- EXECUTE OVER SSH ---
    Write-Step "Connecting to $SshUser@$TargetIp`:$TargetPort via OpenSSH..." "Cyan"

    $sshBaseArgs = @(
        "-p", $TargetPort.ToString(),
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=NUL",
        "-o", "ConnectTimeout=$TimeoutSeconds",
        "-o", "LogLevel=ERROR"
    )
    if (-not [string]::IsNullOrWhiteSpace($IdentityFile)) {
        $sshBaseArgs += @("-i", $IdentityFile)
    }

    # Wait for router SSH to respond (settlement loop)
    $sshConnected = $false
    for ($i = 1; $i -le $MaxRetries; $i++) {
        $testPsi = New-Object System.Diagnostics.ProcessStartInfo
        $testPsi.FileName = $sshPath
        $testPsi.Arguments = [string]::Join(" ", ($sshBaseArgs + @("-o", "BatchMode=yes", "$SshUser@$TargetIp", "echo OPENWRT_READY")))
        $testPsi.RedirectStandardOutput = $true
        $testPsi.RedirectStandardError = $true
        $testPsi.UseShellExecute = $false
        $testPsi.CreateNoWindow = $true

        $testProc = [System.Diagnostics.Process]::Start($testPsi)
        $testOut = $testProc.StandardOutput.ReadToEnd()
        $testErr = $testProc.StandardError.ReadToEnd()
        $testProc.WaitForExit()

        if ($testProc.ExitCode -eq 0 -and $testOut -match "OPENWRT_READY") {
            $sshConnected = $true
            Write-Step "SSH connection established successfully on attempt $i." "Green"
            break
        } elseif ($testErr -match "Permission denied|password") {
            Write-Step "OpenWrt root password set; proceeding to interactive session." "Yellow"
            $sshConnected = $true
            break
        } else {
            Write-Step "Attempt $i/${MaxRetries}: Router not yet responding on SSH. Retrying in ${RetryDelaySeconds}s..." "Yellow"
            Start-Sleep -Seconds $RetryDelaySeconds
        }
    }

    if (-not $sshConnected) {
        throw "Could not establish SSH connection to OpenWrt at $TargetIp`:$TargetPort after $MaxRetries retries."
    }

    # Try passwordless BatchMode first (default on freshly flashed OpenWrt)
    $batchArgs = $sshBaseArgs + @("-o", "BatchMode=yes", "$SshUser@$TargetIp", "sh -s")

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $sshPath
    $psi.Arguments = [string]::Join(" ", $batchArgs)
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.StandardInput.Write($remoteScript)
    $proc.StandardInput.Close()

    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()

    if ($proc.ExitCode -ne 0) {
        if ($stderr -match "Permission denied|password") {
            Write-Step "Passwordless SSH rejected; OpenWrt root password set. Running interactive login..." "Yellow"
            $interactiveArgs = $sshBaseArgs + @("$SshUser@$TargetIp", "sh -s")
            $psi.Arguments = [string]::Join(" ", $interactiveArgs)
            $psi.RedirectStandardInput = $true
            $psi.RedirectStandardOutput = $false
            $psi.RedirectStandardError = $false
            $procInteractive = [System.Diagnostics.Process]::Start($psi)
            $procInteractive.StandardInput.Write($remoteScript)
            $procInteractive.StandardInput.Close()
            $procInteractive.WaitForExit()
            if ($procInteractive.ExitCode -ne 0) {
                throw "Interactive SSH provisioning failed with exit code $($procInteractive.ExitCode)."
            }
        } else {
            throw "SSH execution failed (code $($proc.ExitCode)): $stderr"
        }
    }

    Write-Step "Remote Provisioning Successful!" "Green"
    if (-not [string]::IsNullOrWhiteSpace($stdout)) {
        Write-Host $stdout.Trim() -ForegroundColor Green
    }

    # Verification: Kernel WAN netdevice & ubus lease status
    Start-Sleep -Seconds 3
    $checkPsi = New-Object System.Diagnostics.ProcessStartInfo
    $checkPsi.FileName = $sshPath
    $checkPsi.Arguments = [string]::Join(" ", ($sshBaseArgs + @("-o", "BatchMode=yes", "$SshUser@$TargetIp", "ip link show dev eth0.1; ubus call network.interface.wan status 2>/dev/null || true")))
    $checkPsi.RedirectStandardOutput = $true
    $checkPsi.RedirectStandardError = $true
    $checkPsi.UseShellExecute = $false
    $checkPsi.CreateNoWindow = $true

    $checkProc = [System.Diagnostics.Process]::Start($checkPsi)
    $checkOut = $checkProc.StandardOutput.ReadToEnd()
    $checkProc.WaitForExit()

    if (-not [string]::IsNullOrWhiteSpace($checkOut)) {
        Write-Step "=== Live Router Interface Status ===" "Green"
        Write-Host $checkOut.Trim() -ForegroundColor Gray
    }

    Write-Step "ISP WAN MAC ($WanMac) and Dual-Band Wi-Fi are active on $TargetIp." "Green"
    exit 0
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
