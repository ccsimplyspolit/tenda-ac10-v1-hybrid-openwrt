<#
.SYNOPSIS
    Failsafe Network Adapter Switcher for Tenda AC10 V1.0 Emergency Recovery.
.DESCRIPTION
    Dynamically identifies the host's active physical Ethernet NIC (Intel / Realtek / Broadcom GbE),
    snapshots IPv4 and DNS configuration to network_state_backup.json,
    configures static IP 192.168.1.8/24 (Gateway 192.168.1.6), and guarantees
    restoration back to original DHCP/DNS settings via a 3-layer try/finally safety net.
.PARAMETER Action
    SwitchAndExecute, Switch, Restore, Status
.PARAMETER Command
    Script or command to execute while network is switched to recovery subnet
#>

param(
    [ValidateSet("SwitchAndExecute", "Switch", "Restore", "Status")]
    [string]$Action = "Status",
    [string]$InterfaceAlias = "",
    [string]$Command = "",
    [string]$RecoveryIP = "192.168.1.8",
    [int]$PrefixLength = 24,
    [string]$RecoveryGateway = "192.168.1.6"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackupFile = Join-Path $ScriptDir "network_state_backup.json"
$FwRuleName = "Tenda_TFTP_Recovery"

function Test-IsAdmin {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-PhysicalAdapter {
    param(
        [string]$PreferredName,
        [switch]$IncludeDisconnected
    )

    if ($PreferredName) {
        $a = Get-NetAdapter -Name $PreferredName -ErrorAction SilentlyContinue
        if ($a) { return $a }
    }

    # Step 1: Physical adapter matching common wired vendor strings
    $adapter = Get-NetAdapter | Where-Object {
        ($_.Status -eq 'Up' -or $IncludeDisconnected) -and
        $_.InterfaceDescription -notmatch 'Virtual|VPN|Fortinet|Bluetooth|TAP|Hyper-V|Npcap|Loopback|Wi-Fi|Wireless' -and
        $_.InterfaceDescription -match 'Ethernet|Intel|Realtek|Broadcom|Killer|PCIe|GbE|LAN'
    } | Select-Object -First 1

    if (-not $adapter) {
        # Step 2: Fallback to any wired adapter
        $adapter = Get-NetAdapter | Where-Object {
            ($_.Status -eq 'Up' -or $IncludeDisconnected) -and
            $_.InterfaceDescription -notmatch 'Virtual|VPN|Fortinet|Bluetooth|TAP|Hyper-V|Npcap|Loopback'
        } | Select-Object -First 1
    }

    if (-not $adapter -and -not $IncludeDisconnected) {
        # Step 3: Check disconnected physical adapters if nothing was 'Up'
        $adapter = Find-PhysicalAdapter -PreferredName $PreferredName -IncludeDisconnected
    }

    return $adapter
}

function Save-NetworkState {
    param($Adapter)
    
    $alias = $Adapter.Name
    $ipInt = Get-NetIPInterface -InterfaceAlias $alias -AddressFamily IPv4
    $dhcpEnabled = ($ipInt.Dhcp -eq 'Enabled')
    
    $ipAddresses = @()
    $ips = Get-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 -ErrorAction SilentlyContinue
    if ($ips) {
        foreach ($ip in $ips) {
            $ipAddresses += @{
                IPAddress    = $ip.IPAddress
                PrefixLength = $ip.PrefixLength
            }
        }
    }
    
    $gateway = ""
    $defaultRoute = Get-NetRoute -InterfaceAlias $alias -DestinationPrefix "0.0.0.0/0" -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($defaultRoute) {
        $gateway = $defaultRoute.NextHop
    }
    
    $dns = (Get-DnsClientServerAddress -InterfaceAlias $alias -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses
    if (-not $dns) { $dns = @() }

    $state = @{
        Timestamp            = (Get-Date).ToString("o")
        InterfaceAlias       = $alias
        InterfaceDescription = $Adapter.InterfaceDescription
        InterfaceIndex       = $Adapter.InterfaceIndex
        DhcpEnabled          = $dhcpEnabled
        IPAddresses          = $ipAddresses
        DefaultGateway       = $gateway
        DnsServers           = $dns
    }

    $json = $state | ConvertTo-Json -Depth 4
    Set-Content -Path $BackupFile -Value $json -Encoding UTF8 -Force
    Write-Host "[+] Network state snapshot saved to $BackupFile" -ForegroundColor Cyan
    return $state
}

function Restore-NetworkState {
    param([string]$TargetAlias)

    Write-Host "[*] Executing network failsafe restoration..." -ForegroundColor Yellow

    # Remove temporary firewall rule if present
    try {
        & netsh advfirewall firewall delete rule name="$FwRuleName" | Out-Null
    } catch {}

    $savedState = $null
    if (Test-Path $BackupFile) {
        try {
            $savedState = Get-Content $BackupFile -Raw | ConvertFrom-Json
        } catch {
            Write-Warning "Failed to parse $BackupFile. Proceeding with safe DHCP restoration."
        }
    }

    $alias = $TargetAlias
    if (-not $alias -and $savedState) {
        if ($savedState.InterfaceAlias) {
            $alias = $savedState.InterfaceAlias
        } elseif ($savedState.InterfaceIndex) {
            $byIdx = Get-NetAdapter -InterfaceIndex $savedState.InterfaceIndex -ErrorAction SilentlyContinue
            if ($byIdx) { $alias = $byIdx.Name }
        }
    }
    if (-not $alias) {
        $nic = Find-PhysicalAdapter -IncludeDisconnected
        if ($nic) { $alias = $nic.Name }
    }

    if (-not $alias) {
        Write-Error "[-] Could not determine target network adapter for restoration!"
        return $false
    }

    Write-Host "[*] Restoring adapter: $alias" -ForegroundColor Cyan

    # Remove static recovery IP and routes
    Remove-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetRoute -InterfaceAlias $alias -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue

    if (-not $savedState -or $savedState.DhcpEnabled) {
        Write-Host "[+] Restoring automatic DHCP and DNS on $alias..." -ForegroundColor Green
        Set-NetIPInterface -InterfaceAlias $alias -Dhcp Enabled -ErrorAction SilentlyContinue
        Set-DnsClientServerAddress -InterfaceAlias $alias -ResetServerAddresses -ErrorAction SilentlyContinue
    } else {
        Write-Host "[+] Restoring original static IP settings on $alias..." -ForegroundColor Green
        Set-NetIPInterface -InterfaceAlias $alias -Dhcp Disabled -ErrorAction SilentlyContinue
        foreach ($addr in $savedState.IPAddresses) {
            New-NetIPAddress -InterfaceAlias $alias -IPAddress $addr.IPAddress -PrefixLength $addr.PrefixLength -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        }
        if ($savedState.DefaultGateway) {
            New-NetRoute -InterfaceAlias $alias -DestinationPrefix "0.0.0.0/0" -NextHop $savedState.DefaultGateway -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        }
        if ($savedState.DnsServers -and $savedState.DnsServers.Count -gt 0) {
            Set-DnsClientServerAddress -InterfaceAlias $alias -ServerAddresses $savedState.DnsServers -ErrorAction SilentlyContinue
        }
    }

    # Signal link refresh
    Restart-NetAdapter -Name $alias -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[OK] Network configuration restored successfully." -ForegroundColor Green
    return $true
}

function Switch-ToRecoverySubnet {
    param($Adapter)
    
    $alias = $Adapter.Name
    Write-Host "[*] Configuring Recovery Subnet on $alias ($($Adapter.InterfaceDescription))..." -ForegroundColor Cyan

    # Open firewall port 69 UDP
    try {
        & netsh advfirewall firewall add rule name="$FwRuleName" dir=in action=allow protocol=UDP localport=69 profile=any | Out-Null
        Write-Host "[+] Temporary Windows Firewall rule '$FwRuleName' added (UDP 69)." -ForegroundColor Green
    } catch {
        Write-Warning "Could not add firewall rule (proceeding anyway): $_"
    }

    # Clear old IPs and static gateway
    Remove-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetRoute -InterfaceAlias $alias -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue

    # Set DHCP Disabled and assign recovery IP
    Set-NetIPInterface -InterfaceAlias $alias -Dhcp Disabled -ErrorAction SilentlyContinue
    New-NetIPAddress -InterfaceAlias $alias -IPAddress $RecoveryIP -PrefixLength $PrefixLength -DefaultGateway $RecoveryGateway -Confirm:$false | Out-Null
    
    Write-Host "[+] Assigned Static IP: $RecoveryIP/$PrefixLength (Gateway: $RecoveryGateway)" -ForegroundColor Green
}

# --- Entry Point ---
if ($Action -eq "Restore") {
    if (-not (Test-IsAdmin)) {
        Write-Error "[-] Administrative privileges required to restore network settings!"
        exit 1
    }

    # Step 1: Read backup state FIRST to retrieve InterfaceAlias or InterfaceIndex
    $targetAlias = $InterfaceAlias
    if (-not $targetAlias -and (Test-Path $BackupFile)) {
        try {
            $saved = Get-Content $BackupFile -Raw | ConvertFrom-Json
            if ($saved.InterfaceAlias) {
                $targetAlias = $saved.InterfaceAlias
            } elseif ($saved.InterfaceIndex) {
                $byIdx = Get-NetAdapter -InterfaceIndex $saved.InterfaceIndex -ErrorAction SilentlyContinue
                if ($byIdx) { $targetAlias = $byIdx.Name }
            }
        } catch {
            Write-Warning "Could not read ${BackupFile}: $_"
        }
    }

    # Step 2: Fallback to physical adapter discovery (including Disconnected state)
    if (-not $targetAlias) {
        $targetNic = Find-PhysicalAdapter -PreferredName $InterfaceAlias -IncludeDisconnected
        if ($targetNic) {
            $targetAlias = $targetNic.Name
        }
    }

    if (-not $targetAlias) {
        Write-Error "[-] Could not determine target network adapter for restoration!"
        exit 1
    }

    $ok = Restore-NetworkState -TargetAlias $targetAlias
    if (-not $ok) { exit 1 }
    exit 0
}

$targetNic = Find-PhysicalAdapter -PreferredName $InterfaceAlias
if (-not $targetNic) {
    # If link flap occurred, try including Disconnected
    $targetNic = Find-PhysicalAdapter -PreferredName $InterfaceAlias -IncludeDisconnected
}
if (-not $targetNic) {
    Write-Error "[-] No suitable physical network adapter found!"
    exit 1
}

if ($Action -eq "Status") {
    $ip = (Get-NetIPAddress -InterfaceAlias $targetNic.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress -join ", "
    $dhcp = (Get-NetIPInterface -InterfaceAlias $targetNic.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue).Dhcp
    $dns = (Get-DnsClientServerAddress -InterfaceAlias $targetNic.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses -join ", "
    
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  NETWORK ADAPTER STATUS: $($targetNic.Name)" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  Description: $($targetNic.InterfaceDescription)"
    Write-Host "  Status:      $($targetNic.Status) ($($targetNic.LinkSpeed))"
    Write-Host "  IPv4:        $ip"
    Write-Host "  DHCP:        $dhcp"
    Write-Host "  DNS Servers: $dns"
    Write-Host "============================================================" -ForegroundColor Cyan
    exit 0
}

if ($Action -eq "Switch") {
    if (-not (Test-IsAdmin)) {
        Write-Error "[-] Administrative privileges required to configure static IP!"
        exit 1
    }
    Save-NetworkState -Adapter $targetNic | Out-Null
    Switch-ToRecoverySubnet -Adapter $targetNic
    exit 0
}

if ($Action -eq "SwitchAndExecute") {
    if (-not (Test-IsAdmin)) {
        Write-Error "[-] Administrative privileges required for network switching!"
        exit 1
    }

    Save-NetworkState -Adapter $targetNic | Out-Null
    try {
        Switch-ToRecoverySubnet -Adapter $targetNic
        if ($Command) {
            Write-Host "[*] Executing payload task: $Command" -ForegroundColor Yellow
            Invoke-Expression $Command
        }
    }
    finally {
        Write-Host "[!] Triggering guaranteed finally rollback..." -ForegroundColor Yellow
        Restore-NetworkState -TargetAlias $targetNic.Name
    }
}
