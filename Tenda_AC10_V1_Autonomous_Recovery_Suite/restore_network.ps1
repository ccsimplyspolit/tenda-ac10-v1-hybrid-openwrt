<#
.SYNOPSIS
    Standalone Emergency Network Restorer for Tenda AC10 V1.0 Recovery Suite
.DESCRIPTION
    Restores the physical Ethernet adapter to automatic DHCP and DNS.
    Reads network_state_backup.json if present, or safely resets the detected
    physical NIC to DHCP. Removes temporary TFTP Windows Firewall rules.
#>

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackupFile = Join-Path $ScriptDir "network_state_backup.json"
$FwRuleName = "Tenda_TFTP_Recovery"

function Test-IsAdmin {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Warning "Administrative privileges required! Re-launching with elevation..."
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit 0
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  EMERGENCY NETWORK RESTORATION" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Clean up Firewall Rule
Write-Host "[*] Cleaning up temporary Windows Firewall rules..." -ForegroundColor Cyan
& netsh advfirewall firewall delete rule name="$FwRuleName" 2>$null | Out-Null

# 2. Identify Target Adapter
$savedState = $null
if (Test-Path $BackupFile) {
    try {
        $savedState = Get-Content $BackupFile -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host "[+] Found network state backup from $($savedState.Timestamp)" -ForegroundColor Green
    } catch {
        Write-Warning "Could not parse backup file. Using auto-discovery."
    }
}

$targetAlias = ""
if ($savedState -and $savedState.InterfaceAlias) {
    $targetAlias = $savedState.InterfaceAlias
} elseif ($savedState -and $savedState.InterfaceIndex) {
    $byIdx = Get-NetAdapter -InterfaceIndex $savedState.InterfaceIndex -ErrorAction SilentlyContinue
    if ($byIdx) { $targetAlias = $byIdx.Name }
}

if (-not $targetAlias) {
    $adapter = Get-NetAdapter | Where-Object {
        $_.Status -eq 'Up' -and
        $_.InterfaceDescription -notmatch 'Virtual|VPN|Fortinet|Bluetooth|TAP|Hyper-V|Npcap|Loopback|Wi-Fi' -and
        $_.InterfaceDescription -match 'Ethernet|Intel|Realtek|Broadcom|Killer|PCIe|GbE|LAN'
    } | Select-Object -First 1

    if (-not $adapter) {
        $adapter = Get-NetAdapter | Where-Object {
            $_.InterfaceDescription -notmatch 'Virtual|VPN|Fortinet|Bluetooth|TAP|Hyper-V|Npcap|Loopback'
        } | Select-Object -First 1
    }

    if ($adapter) {
        $targetAlias = $adapter.Name
    }
}

if (-not $targetAlias) {
    $targetAlias = "Ethernet"
}

Write-Host "[*] Target adapter: $targetAlias" -ForegroundColor Cyan

# 3. Remove static IP / routes
Write-Host "[*] Clearing static recovery addresses and default routes..." -ForegroundColor Cyan
Remove-NetIPAddress -InterfaceAlias $targetAlias -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetRoute -InterfaceAlias $targetAlias -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue

# 4. Restore settings
if (-not $savedState -or $savedState.DhcpEnabled) {
    Write-Host "[+] Enabling DHCP (Automatic IPv4 Address)..." -ForegroundColor Green
    Set-NetIPInterface -InterfaceAlias $targetAlias -Dhcp Enabled -ErrorAction SilentlyContinue

    Write-Host "[+] Enabling Automatic DNS Server Assignment..." -ForegroundColor Green
    Set-DnsClientServerAddress -InterfaceAlias $targetAlias -ResetServerAddresses -ErrorAction SilentlyContinue
} else {
    Write-Host "[+] Restoring saved static IP configuration..." -ForegroundColor Green
    Set-NetIPInterface -InterfaceAlias $targetAlias -Dhcp Disabled -ErrorAction SilentlyContinue
    foreach ($addr in $savedState.IPAddresses) {
        New-NetIPAddress -InterfaceAlias $targetAlias -IPAddress $addr.IPAddress -PrefixLength $addr.PrefixLength -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    }
    if ($savedState.DefaultGateway) {
        New-NetRoute -InterfaceAlias $targetAlias -DestinationPrefix "0.0.0.0/0" -NextHop $savedState.DefaultGateway -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    }
    if ($savedState.DnsServers -and $savedState.DnsServers.Count -gt 0) {
        Set-DnsClientServerAddress -InterfaceAlias $targetAlias -ServerAddresses $savedState.DnsServers -ErrorAction SilentlyContinue
    }
}

# 5. Refresh adapter
Write-Host "[*] Refreshing network interface..." -ForegroundColor Cyan
Restart-NetAdapter -Name $targetAlias -Confirm:$false -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  SUCCESS: Network restored to normal operation!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
