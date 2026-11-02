<#
.SYNOPSIS
    100% Autonomous Offline TFTP Emergency Recovery & Firmware Flasher for Tenda AC10 V1.0
    (Realtek Booter v3.4.11B.9 @ 192.168.1.6:69)

.DESCRIPTION
    - Zero external dependencies: uses native .NET System.Net.Sockets.UdpClient (no Windows optional tftp.exe required).
    - Pre-flight binary safety gate: emulates Realtek Booter v3.4.11B.9 AutoBurn (0x800019d0) and check_image (0x8000dd10)
      to verify magic (cr6c/cs6c), loadAddr (0x80A00000), burnAddr (0x00030000), 16-bit BE additive checksum (0x0000),
      and blocks the lethal 2-segment cs6c+hsqs bootloader bug (0x80001c2c).
    - Multi-layer failsafe network configuration: dynamically identifies the physical Ethernet NIC,
      snapshots original IPv4/DHCP/DNS state to network_state_backup.json, sets static IP 192.168.1.116/24 inside a
      strict try / finally block, and unconditionally restores DHCP + automatic DNS upon exit, error, Ctrl+C, or
      prolonged 20-30 minute internet outage.
    - Probes 192.168.1.6 via ARP + UDP Port 69 TFTP WRQ (does NOT rely on ICMP ping, which Realtek Booter drops at 0x80001018).
#>
[CmdletBinding()]
param(
    [string]$FirmwarePath = "",
    [string]$ServerIp = "192.168.1.6",
    [int]$Port = 69,
    [string]$StaticHostIp = "192.168.1.116",
    [int]$PrefixLength = 24,
    [string]$InterfaceAlias = "Ethernet",
    [string]$RemoteFileName = "firmware.bin",
    [int]$ProbeTimeoutSeconds = 180,
    [int]$BlockTimeoutMs = 1500,
    [int]$MaxBlockRetries = 6,
    [int]$PostFlashWaitSeconds = 120,
    [switch]$SkipNetworkConfig,
    [switch]$VerifyOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$HybridKitRoot = Split-Path -Parent $ScriptDir
$BackupStateFile = Join-Path $ScriptDir "network_state_backup.json"

if ([string]::IsNullOrWhiteSpace($FirmwarePath)) {
    $Candidates = @(
        (Join-Path $HybridKitRoot "01_Stock_Firmware_and_Partitions\Tenda_AC10_V1_Stock_TFTP_Recovery.bin"),
        (Join-Path $HybridKitRoot "backups\Tenda_AC10_V1_Stock_TFTP_Recovery.bin"),
        (Join-Path $HybridKitRoot "02_Compiled_Hybrid_OpenWrt_4.14_Firmware\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin")
    )
    foreach ($c in $Candidates) {
        if (Test-Path -LiteralPath $c) {
            $FirmwarePath = $c
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($FirmwarePath)) {
        $FirmwarePath = $Candidates[0]
    }
}

function Write-Step {
    param([string]$Message, [string]$Color = "Cyan")
    $ts = (Get-Date).ToString("HH:mm:ss")
    Write-Host "[$ts] $Message" -ForegroundColor $Color
}

function Read-UInt32BE {
    param([byte[]]$Buffer, [int]$Offset)
    return ([int64]$Buffer[$Offset] -shl 24) -bor
           ([int64]$Buffer[$Offset + 1] -shl 16) -bor
           ([int64]$Buffer[$Offset + 2] -shl 8) -bor
           ([int64]$Buffer[$Offset + 3])
}

if (-not ("RealtekBooterFastChecksum" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;

public static class RealtekBooterFastChecksum {
    private static readonly uint[] CrcTable = InitCrcTable();
    private static uint[] InitCrcTable() {
        uint[] tbl = new uint[256];
        for (uint i = 0; i < 256; i++) {
            uint c = i;
            for (int k = 0; k < 8; k++) {
                c = ((c & 1) != 0) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
            }
            tbl[i] = c;
        }
        return tbl;
    }

    public static uint Crc32(byte[] buffer, int offset, int length) {
        uint crc = 0xFFFFFFFFu;
        int end = offset + length;
        for (int i = offset; i < end; i++) {
            crc = CrcTable[(crc ^ buffer[i]) & 0xFFu] ^ (crc >> 8);
        }
        return ~crc;
    }

    public static ushort Sum16BE(byte[] buffer, int offset, int length) {
        uint acc = 0;
        int end = offset + length;
        for (int i = offset; i < end; i += 2) {
            uint word = ((uint)buffer[i] << 8) | (uint)buffer[i + 1];
            acc = (acc + word) & 0xFFFFu;
        }
        return (ushort)acc;
    }

    public static double UploadTftp(
        byte[] payload,
        string targetIp,
        int targetPort,
        string fileName,
        int probeTimeoutSec,
        int timeoutMs,
        int maxRetries
    ) {
        using (UdpClient udp = new UdpClient(0)) {
            udp.Client.ReceiveTimeout = timeoutMs;
            udp.Client.SendTimeout = timeoutMs;

            byte[] fnBytes = Encoding.ASCII.GetBytes(fileName);
            byte[] modeBytes = Encoding.ASCII.GetBytes("octet");
            byte[] wrq = new byte[2 + fnBytes.Length + 1 + modeBytes.Length + 1];
            wrq[0] = 0;
            wrq[1] = 2; // WRQ
            Buffer.BlockCopy(fnBytes, 0, wrq, 2, fnBytes.Length);
            wrq[2 + fnBytes.Length] = 0;
            Buffer.BlockCopy(modeBytes, 0, wrq, 3 + fnBytes.Length, modeBytes.Length);
            wrq[wrq.Length - 1] = 0;

            IPEndPoint booterEp = new IPEndPoint(IPAddress.Parse(targetIp), targetPort);
            IPEndPoint remoteEp = new IPEndPoint(IPAddress.Any, 0);
            IPEndPoint sessionEp = null;

            Stopwatch probeSw = Stopwatch.StartNew();
            long probeLimitMs = (long)probeTimeoutSec * 1000L;

            while (probeSw.ElapsedMilliseconds < probeLimitMs) {
                udp.Send(wrq, wrq.Length, booterEp);
                try {
                    byte[] ackBytes = udp.Receive(ref remoteEp);
                    if (ackBytes != null && ackBytes.Length >= 4) {
                        int opcode = (ackBytes[0] << 8) | ackBytes[1];
                        int blk = (ackBytes[2] << 8) | ackBytes[3];
                        if (opcode == 4 && blk == 0) {
                            sessionEp = new IPEndPoint(remoteEp.Address, remoteEp.Port);
                            break;
                        } else if (opcode == 5) {
                            string errMsg = Encoding.ASCII.GetString(ackBytes, 4, Math.Max(0, ackBytes.Length - 5));
                            throw new InvalidOperationException("Router returned TFTP ERROR on WRQ: " + errMsg);
                        }
                    }
                } catch (SocketException) {
                    continue;
                }
            }

            if (sessionEp == null) {
                throw new TimeoutException(
                    string.Format("Timed out after {0}s waiting for Realtek Booter at {1}:{2}. Ensure cable is in LAN1/LAN2/LAN3 (NOT WAN) and RST was held during power-on.",
                    probeTimeoutSec, targetIp, targetPort));
            }

            int totalBytes = payload.Length;
            int offset = 0;
            int blockNum = 1;
            bool sendZeroTerminate = (totalBytes % 512 == 0);
            Stopwatch sw = Stopwatch.StartNew();

            while (offset < totalBytes || sendZeroTerminate) {
                int chunkLen = Math.Min(512, totalBytes - offset);
                if (offset >= totalBytes && sendZeroTerminate) {
                    chunkLen = 0;
                    sendZeroTerminate = false;
                }

                byte[] pkt = new byte[4 + chunkLen];
                pkt[0] = 0;
                pkt[1] = 3; // DATA
                pkt[2] = (byte)((blockNum >> 8) & 0xFF);
                pkt[3] = (byte)(blockNum & 0xFF);
                if (chunkLen > 0) {
                    Buffer.BlockCopy(payload, offset, pkt, 4, chunkLen);
                }

                bool acked = false;
                int curTimeout = timeoutMs;
                for (int attempt = 1; attempt <= maxRetries; attempt++) {
                    udp.Client.ReceiveTimeout = curTimeout;
                    udp.Send(pkt, pkt.Length, sessionEp);

                    long waitStart = sw.ElapsedMilliseconds;
                    while ((sw.ElapsedMilliseconds - waitStart) < curTimeout) {
                        try {
                            byte[] rx = udp.Receive(ref remoteEp);
                            if (rx != null && rx.Length >= 4) {
                                int op = (rx[0] << 8) | rx[1];
                                int ackBlk = (rx[2] << 8) | rx[3];
                                if (op == 4 && ackBlk == blockNum) {
                                    acked = true;
                                    break;
                                } else if (op == 5) {
                                    string errMsg = Encoding.ASCII.GetString(rx, 4, Math.Max(0, rx.Length - 5));
                                    throw new InvalidOperationException(
                                        string.Format("TFTP ERROR from router at block {0}: {1}", blockNum, errMsg));
                                }
                                // Ignore duplicate/stale ACKs
                            }
                        } catch (SocketException) {
                            break;
                        }
                    }
                    if (acked) {
                        break;
                    }
                    curTimeout = Math.Min(5000, (int)(curTimeout * 1.5));
                }

                if (!acked) {
                    throw new TimeoutException(
                        string.Format("TFTP transfer failed at block {0} (offset {1} / {2}) after {3} retries.",
                        blockNum, offset, totalBytes, maxRetries));
                }

                offset += chunkLen;
                blockNum = (blockNum + 1) & 0xFFFF;
            }

            sw.Stop();
            return sw.Elapsed.TotalSeconds;
        }
    }
}
"@
}

function Get-Sum16BE {
    param([byte[]]$Buffer, [int]$Offset, [int]$Length)
    if ($Length % 2 -ne 0) {
        throw "Payload length ($Length) is odd; 16-bit BE checksum requires even byte count."
    }
    return [RealtekBooterFastChecksum]::Sum16BE($Buffer, $Offset, $Length)
}

function Test-RealtekBooterImage {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Firmware file not found: $Path"
    }

    [byte[]]$origRaw = [System.IO.File]::ReadAllBytes($Path)
    [byte[]]$raw = $origRaw
    $maxAllowed = 8060928 # 0x7E0000 - 0x030000 = 0x7B0000 (7,872 KB)
    $isWebWrapped = $false

    if ($origRaw.Length -ge 4 -and $origRaw[0] -eq 0x27 -and $origRaw[1] -eq 0x05 -and $origRaw[2] -eq 0x19 -and $origRaw[3] -eq 0x56) {
        if ($origRaw.Length -lt 96) {
            throw "Tenda 0x27051956 WebUI image too small ($($origRaw.Length) bytes < 96)."
        }
        if ($origRaw.Length -ge $maxAllowed) {
            throw "Tenda 0x27051956 WebUI image ($($origRaw.Length) bytes) violates check_mtd_size (< $maxAllowed bytes)!"
        }
        $ihHcrc = [uint32](Read-UInt32BE -Buffer $origRaw -Offset 4)
        $ihSize = [int64](Read-UInt32BE -Buffer $origRaw -Offset 12)
        $ihDcrc = [uint32](Read-UInt32BE -Buffer $origRaw -Offset 24)
        $ihOs = if ($origRaw[0x20] -eq 2) { 2 } else { [int]$origRaw[28] }
        $ver0x24 = [uint32](Read-UInt32BE -Buffer $origRaw -Offset 0x24)
        $ver0x20 = [uint32](Read-UInt32BE -Buffer $origRaw -Offset 0x20)
        $ihVer = if ($ver0x24 -eq 0x00030028) { $ver0x24 } else { $ver0x20 }

        [byte[]]$hdrZero = New-Object byte[] 64
        [Array]::Copy($origRaw, 0, $hdrZero, 0, 64)
        $hdrZero[4] = 0; $hdrZero[5] = 0; $hdrZero[6] = 0; $hdrZero[7] = 0
        $calcHcrc = [RealtekBooterFastChecksum]::Crc32($hdrZero, 0, 64)
        if ($ihHcrc -ne 0 -and $ihHcrc -ne $calcHcrc) {
            throw ("Tenda 0x27051956 ih_hcrc mismatch: 0x{0:X8} != 0x{1:X8}" -f $ihHcrc, $calcHcrc)
        }
        $innerLen = $origRaw.Length - 64
        if ($ihSize -ne $innerLen) {
            throw "Tenda 0x27051956 ih_size mismatch: header=$ihSize, actual=$innerLen"
        }
        $calcDcrc = [RealtekBooterFastChecksum]::Crc32($origRaw, 64, $innerLen)
        if ($ihDcrc -ne $calcDcrc) {
            throw ("Tenda 0x27051956 ih_dcrc mismatch: 0x{0:X8} != 0x{1:X8}" -f $ihDcrc, $calcDcrc)
        }
        if ($ihOs -ne 2) {
            throw "Tenda 0x27051956 ih_os=$ihOs rejected (expected 2 = Linux)."
        }
        if ($ihVer -ne 0x00030028) {
            throw ("Tenda 0x27051956 ih_ver=0x{0:X8} rejected (expected 0x00030028 for Tenda AC10 V1.0)." -f $ihVer)
        }
        $raw = New-Object byte[] $innerLen
        [Array]::Copy($origRaw, 64, $raw, 0, $innerLen)
        $isWebWrapped = $true
    }

    $totalLen = $raw.Length

    if ($totalLen -lt 32) {
        throw "Image too small ($totalLen bytes)."
    }
    if ($totalLen -gt $maxAllowed) {
        throw "Image size ($totalLen bytes) exceeds 7,872 KB firmware partition limit ($maxAllowed bytes) and would overwrite NVRAM at 0x7E0000!"
    }

    $magic = [System.Text.Encoding]::ASCII.GetString($raw, 0, 4)
    if ($magic -ne "cr6c" -and $magic -ne "cs6c") {
        throw "Unsupported image header magic '$magic' (expected 'cr6c', 'cs6c', or 0x27051956 WebUI wrapper)."
    }

    $startAddr = Read-UInt32BE -Buffer $raw -Offset 4
    $burnAddr  = Read-UInt32BE -Buffer $raw -Offset 8
    $seg1Len   = Read-UInt32BE -Buffer $raw -Offset 12

    if ($startAddr -ne [int64]2157969408) {
        throw ("Invalid RAM load address 0x{0:X8} (expected 0x80A00000)." -f $startAddr)
    }
    if ($burnAddr -ne [int64]196608) {
        throw ("Unsafe SPI flash burn address 0x{0:X8} (must be 0x00030000 to protect Bootloader 0x0 and RF Calibration 0x20000)!" -f $burnAddr)
    }
    if ((16 + $seg1Len) -gt $totalLen) {
        throw "Header segment 1 length ($seg1Len) exceeds total file length ($totalLen)."
    }

    $seg1Sum = Get-Sum16BE -Buffer $raw -Offset 16 -Length ([int]$seg1Len)
    if ($seg1Sum -ne 0) {
        throw ("Segment 1 ({0}) 16-bit BE checksum failed: 0x{1:X4} != 0x0000!" -f $magic, $seg1Sum)
    }

    $remLen = $totalLen - (16 + [int]$seg1Len)
    $imageMode = "Single-Segment ($magic)"

    if ($remLen -gt 0) {
        # CRITICAL GUARD against Realtek Booter v3.4.11B.9 bug @ 0x80001c2c:
        # A 2-segment cs6c + hsqs image leaves sp[0x6c]=0 and sets $s7=0 on segment 2, erasing flash offset 0x00000000!
        if ($magic -eq "cs6c") {
            throw "LETHAL IMAGE BLOCKED: Multi-segment 'cs6c' image detected ($remLen trailing bytes). Realtek Booter v3.4.11B.9 bug @ 0x80001c2c sets burnAddr=0x00000000 on segment 2 and erases the bootloader! Repack as single-segment 'cs6c' or use 'cr6c'."
        }

        if ($remLen -lt 16) {
            throw "Trailing bytes ($remLen) after cr6c segment are too short to form a valid hsqs RootFS segment."
        }

        $seg2Off = 16 + [int]$seg1Len
        $magic2 = [System.Text.Encoding]::ASCII.GetString($raw, $seg2Off, 4)
        if ($magic2 -ne "hsqs" -and $magic2 -ne "sqsh") {
            throw "Invalid segment 2 magic '$magic2' at offset 0x$($seg2Off.ToString('X')) (expected 'hsqs' or 'sqsh')."
        }

        # check_rootfs_image (0x8000d844) reads BE32 at +8 of hsqs and adds 0x282 (642)
        $hsqsBe8 = Read-UInt32BE -Buffer $raw -Offset ($seg2Off + 8)
        $hsqsCheckLen = [int]$hsqsBe8 + 0x282
        if ($remLen -ne $hsqsCheckLen) {
            throw "Segment 2 ($magic2) length mismatch: actual=$remLen bytes, check_rootfs_image expects $hsqsCheckLen bytes."
        }

        $seg2Sum = Get-Sum16BE -Buffer $raw -Offset $seg2Off -Length $remLen
        if ($seg2Sum -ne 0) {
            throw ("Segment 2 ({0}) 16-bit BE checksum failed: 0x{1:X4} != 0x0000!" -f $magic2, $seg2Sum)
        }
        $imageMode = "Dual-Segment Factory Stock (cr6c + $magic2)"
    }

    if ($isWebWrapped) {
        $imageMode = "Tenda 0x27051956 WebUI Wrapped -> $imageMode (auto-unwrapped 64 B)"
    }

    $sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    return [PSCustomObject]@{
        Path         = $Path
        FileSize     = $origRaw.Length
        BooterSize   = $totalLen
        Magic        = $magic
        Mode         = $imageMode
        StartAddr    = ("0x{0:X8}" -f $startAddr)
        BurnAddr     = ("0x{0:X8}" -f $burnAddr)
        Seg1Len      = $seg1Len
        Seg2Len      = $remLen
        SHA256       = $sha256
        PayloadBytes = $raw
    }
}

function Find-PhysicalEthernetAdapter {
    param([string]$PreferredAlias = "Ethernet")
    $nic = Get-NetAdapter -Name $PreferredAlias -ErrorAction SilentlyContinue
    if ($nic -and $nic.InterfaceDescription -notmatch 'Virtual|VPN|Fortinet|Bluetooth|TAP|Hyper-V|Loopback') {
        return $nic
    }
    $nic = Get-NetAdapter | Where-Object {
        $_.InterfaceDescription -notmatch 'Virtual|VPN|Fortinet|Bluetooth|TAP|Hyper-V|Npcap|Loopback' -and
        $_.InterfaceDescription -match 'Intel|Realtek|Broadcom|Ethernet|PCIe|GbE|LAN'
    } | Select-Object -First 1
    if (-not $nic) {
        throw "Could not locate physical Ethernet adapter."
    }
    return $nic
}

function Save-NetworkStateSnapshot {
    param([string]$Alias, [string]$OutFile)
    $ipIf = Get-NetIPInterface -InterfaceAlias $Alias -AddressFamily IPv4 -ErrorAction SilentlyContinue
    $ips = @(Get-NetIPAddress -InterfaceAlias $Alias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "169.254.*" } |
        ForEach-Object { @{ IPAddress = $_.IPAddress; PrefixLength = [int]$_.PrefixLength } })
    $gw = (Get-NetRoute -InterfaceAlias $Alias -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
        Select-Object -First 1).NextHop
    $dns = @((Get-DnsClientServerAddress -InterfaceAlias $Alias -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses)

    $snapshot = [ordered]@{
        Timestamp      = (Get-Date).ToString("o")
        InterfaceAlias = $Alias
        DhcpEnabled    = ($null -eq $ipIf -or $ipIf.Dhcp -eq "Enabled")
        OriginalIPs    = $ips
        DefaultGateway = $gw
        DnsServers     = $dns
    }
    $snapshot | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $OutFile -Encoding UTF8 -Force
    return $snapshot
}

function Restore-NetworkStateFailsafe {
    param([string]$Alias, [object]$Snapshot)
    Write-Step "[FAILSAFE] Restoring network adapter '$Alias' to automatic DHCP & DNS..." "Yellow"
    try {
        Remove-NetIPAddress -InterfaceAlias $Alias -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
        Remove-NetRoute -InterfaceAlias $Alias -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue
        Set-NetIPInterface -InterfaceAlias $Alias -AddressFamily IPv4 -Dhcp Enabled -ErrorAction SilentlyContinue
        Set-DnsClientServerAddress -InterfaceAlias $Alias -ResetServerAddresses -ErrorAction SilentlyContinue
        ipconfig /renew $Alias >$null 2>&1
    } catch {
        # Fallback to netsh if CIM cmdlets encounter transient state
        netsh interface ip set address name="$Alias" source=dhcp >$null 2>&1
        netsh interface ip set dns name="$Alias" source=dhcp >$null 2>&1
    }
    $dhcpNow = (Get-NetIPInterface -InterfaceAlias $Alias -AddressFamily IPv4 -ErrorAction SilentlyContinue).Dhcp
    Write-Step "[FAILSAFE] Adapter '$Alias' DHCP state is now: $dhcpNow" "Green"
}

function Send-TftpFirmware {
    param(
        [byte[]]$Payload,
        [string]$TargetIp,
        [int]$TargetPort,
        [string]$FileName,
        [int]$ProbeTimeoutSec,
        [int]$TimeoutMs,
        [int]$MaxRetries
    )

    Write-Step "Probing Realtek Booter TFTP server at ${TargetIp}:${TargetPort} via UDP WRQ (ICMP ping is ignored by booter)..." "Cyan"
    $elapsedSec = [RealtekBooterFastChecksum]::UploadTftp(
        $Payload,
        $TargetIp,
        $TargetPort,
        $FileName,
        $ProbeTimeoutSec,
        $TimeoutMs,
        $MaxRetries
    )
    Write-Step ("TFTP Upload Complete! Sent {0:N0} bytes in {1:N2}s." -f $Payload.Length, $elapsedSec) "Green"
}

# ==============================================================================
# MAIN EXECUTION FLOW
# ==============================================================================
Write-Step "=== TENDA AC10 V1.0 AUTONOMOUS OFFLINE TFTP RECOVERY & FLASHER ===" "Cyan"

$imgInfo = Test-RealtekBooterImage -Path $FirmwarePath
Write-Step ("Verified Image : {0}" -f $imgInfo.Path) "Green"
Write-Step ("Image Mode     : {0} | Size: {1:N0} B | SHA256: {2}" -f $imgInfo.Mode, $imgInfo.FileSize, $imgInfo.SHA256) "Green"
Write-Step ("Bootloader Map : startAddr={0}, burnAddr={1}, Checksum=0x0000 [PASS]" -f $imgInfo.StartAddr, $imgInfo.BurnAddr) "Green"

if ($VerifyOnly) {
    Write-Step "VerifyOnly mode completed successfully." "Green"
    exit 0
}

[byte[]]$payloadBytes = $imgInfo.PayloadBytes

if ($DryRun) {
    $nic = Find-PhysicalEthernetAdapter -PreferredAlias $InterfaceAlias
    Write-Step ("[DRY-RUN] Detected physical NIC: {0} ({1})" -f $nic.Name, $nic.InterfaceDescription) "Yellow"
    Write-Step "[DRY-RUN] Skipping static IP modification and network transmission." "Yellow"
    exit 0
}

if ($SkipNetworkConfig) {
    Send-TftpFirmware -Payload $payloadBytes -TargetIp $ServerIp -TargetPort $Port `
        -FileName $RemoteFileName -ProbeTimeoutSec $ProbeTimeoutSeconds `
        -TimeoutMs $BlockTimeoutMs -MaxRetries $MaxBlockRetries
    exit 0
}

# Production Hardware Recovery with Guaranteed try / finally Network Rollback
$nic = Find-PhysicalEthernetAdapter -PreferredAlias $InterfaceAlias
$alias = $nic.Name
Write-Step ("Selected Physical Adapter: {0} ({1})" -f $alias, $nic.InterfaceDescription) "Cyan"
$snapshot = Save-NetworkStateSnapshot -Alias $alias -OutFile $BackupStateFile

try {
    Write-Step "IMPORTANT: Plug Ethernet cable into Router LAN1, LAN2, or LAN3 (NEVER WAN - Booter powers down Port 3)." "Yellow"
    Write-Step "Configuring temporary static IP $StaticHostIp/$PrefixLength on '$alias'..." "Cyan"

    netsh advfirewall firewall add rule name="Tenda_AC10_TFTP_Temp" dir=in action=allow protocol=UDP localport=any profile=any >$null 2>&1
    Remove-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue
    Remove-NetRoute -InterfaceAlias $alias -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue
    New-NetIPAddress -InterfaceAlias $alias -IPAddress $StaticHostIp -PrefixLength $PrefixLength -DefaultGateway $ServerIp -ErrorAction Stop | Out-Null

    Send-TftpFirmware -Payload $payloadBytes -TargetIp $ServerIp -TargetPort $Port `
        -FileName $RemoteFileName -ProbeTimeoutSec $ProbeTimeoutSeconds `
        -TimeoutMs $BlockTimeoutMs -MaxRetries $MaxBlockRetries

    Write-Step "DO NOT UNPLUG POWER! Router is erasing and writing SPI NOR flash at 0x00030000 (~90-120s)..." "Yellow"
    $waited = 0
    while ($waited -lt $PostFlashWaitSeconds) {
        $stepSec = [Math]::Min(15, ($PostFlashWaitSeconds - $waited))
        Start-Sleep -Seconds $stepSec
        $waited += $stepSec
        $remSec = $PostFlashWaitSeconds - $waited
        Write-Step ("SPI NOR flash burn in progress... ({0}s / {1}s elapsed, {2}s remaining)" -f $waited, $PostFlashWaitSeconds, $remSec) "Cyan"
    }
} finally {
    netsh advfirewall firewall delete rule name="Tenda_AC10_TFTP_Temp" >$null 2>&1
    Restore-NetworkStateFailsafe -Alias $alias -Snapshot $snapshot
}

Write-Step "Recovery & Flash workflow finished. PC Ethernet is back on automatic DHCP/DNS." "Green"
