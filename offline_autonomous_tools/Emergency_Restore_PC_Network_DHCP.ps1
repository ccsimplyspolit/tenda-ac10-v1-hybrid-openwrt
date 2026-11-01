<#
.SYNOPSIS
    Emergency Standalone PC Network Adapter DHCP & DNS Restorer (Physical Ethernet Adapter)

.DESCRIPTION
    Immediately restores the physical Ethernet adapter to automatic DHCP and DNS.
    Safe to run at any time if a script was hard-terminated or if the router took 20-30 minutes to come back online.
#>
[CmdletBinding()]
param(
    [string]$InterfaceAlias = "Ethernet",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BackupFile = Join-Path $ScriptDir "network_state_backup.json"

if (Test-Path -LiteralPath $BackupFile) {
    try {
        $snap = Get-Content -LiteralPath $BackupFile -Raw | ConvertFrom-Json
        if ($snap.InterfaceAlias) {
            $InterfaceAlias = $snap.InterfaceAlias
        }
    } catch {}
}

$nic = Get-NetAdapter -Name $InterfaceAlias -ErrorAction SilentlyContinue
if (-not $nic) {
    $nic = Get-NetAdapter | Where-Object {
        $_.InterfaceDescription -notmatch 'Virtual|VPN|Fortinet|Bluetooth|TAP|Hyper-V|Loopback' -and
        $_.InterfaceDescription -match 'Intel|Realtek|Ethernet|PCIe|GbE'
    } | Select-Object -First 1
    if ($nic) { $InterfaceAlias = $nic.Name }
}

$ipIf = Get-NetIPInterface -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -ErrorAction SilentlyContinue
$cfg  = Get-NetIPConfiguration -InterfaceAlias $InterfaceAlias -ErrorAction SilentlyContinue

Write-Host "[INFO] Target Adapter : $InterfaceAlias ($($nic.InterfaceDescription))" -ForegroundColor Cyan
Write-Host "[INFO] Current DHCP   : $($ipIf.Dhcp)" -ForegroundColor Cyan
Write-Host "[INFO] Current IPv4   : $($cfg.IPv4Address.IPAddress -join ', ')" -ForegroundColor Cyan
Write-Host "[INFO] Current Gateway: $($cfg.IPv4DefaultGateway.NextHop -join ', ')" -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "[DRY-RUN] No changes applied to '$InterfaceAlias'." -ForegroundColor Yellow
    exit 0
}

Write-Host "[*] Restoring '$InterfaceAlias' to automatic DHCP and DNS..." -ForegroundColor Yellow
try {
    netsh advfirewall firewall delete rule name="Tenda_AC10_TFTP_Temp" >$null 2>&1
    Remove-NetIPAddress -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetRoute -InterfaceAlias $InterfaceAlias -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue
    Set-NetIPInterface -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -Dhcp Enabled -ErrorAction SilentlyContinue
    Set-DnsClientServerAddress -InterfaceAlias $InterfaceAlias -ResetServerAddresses -ErrorAction SilentlyContinue
    ipconfig /renew $InterfaceAlias >$null 2>&1
} catch {
    netsh interface ip set address name="$InterfaceAlias" source=dhcp >$null 2>&1
    netsh interface ip set dns name="$InterfaceAlias" source=dhcp >$null 2>&1
}

$ipIfAfter = Get-NetIPInterface -InterfaceAlias $InterfaceAlias -AddressFamily IPv4 -ErrorAction SilentlyContinue
Write-Host "[OK] Adapter '$InterfaceAlias' restored (Dhcp = $($ipIfAfter.Dhcp))." -ForegroundColor Green
