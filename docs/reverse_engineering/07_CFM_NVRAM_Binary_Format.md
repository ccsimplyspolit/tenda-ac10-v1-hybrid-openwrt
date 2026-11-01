# CFM Configuration Database & Ping-Pong NVRAM Binary Format

## 1. Executive Subsystem Overview

On the Tenda AC10 V1.0 router, runtime persistent configuration settings (LAN IP, Wi-Fi SSIDs and encryption keys, firewall rules, ISP connection profiles) are stored and arbitrated by the **Configuration Management (`CFM`)** subsystem. This subsystem is implemented across three core components:
- `/bin/cfmd`: The background configuration daemon and IPC message broker.
- `/bin/cfm`: The userspace command-line tool for reading and writing configuration variables (`cfm get <key>`, `cfm set <key> <val>`).
- `libCfm.so`: The shared library providing low-level serialization, CRC32 verification, and flash I/O routines.

Persistent storage utilizes a **Dual-Bank Ping-Pong Flash Architecture** located across the top two 64 KB sectors of the 8 MB SPI NOR Flash chip:
- **Primary CFM Sector (`mtd5`)**: Flash offset `0x007E0000` to `0x007F0000` (65,536 bytes).
- **Backup CFM Sector (`mtd6`)**: Flash offset `0x007F0000` to `0x00800000` (65,536 bytes).

```
+-----------------------------------------------------------------------------------+
|               Dual-Bank Ping-Pong NVRAM Architecture (mtd5 & mtd6)                |
|                                                                                   |
|  Flash 0x7E0000 (mtd5) - 64 KB                    Flash 0x7F0000 (mtd6) - 64 KB   |
|  +--------------------------------+               +--------------------------------+
|  | Header: CRC32 = 0x34E8A155     |               | Header: CRC32 = 0xCA5891A6     |
|  | Sequence Counter = 341 (0x155) |               | Sequence Counter = 340 (0x154) |
|  +--------------------------------+               +--------------------------------+
|  | ASCII Key-Value Configuration: |               | ASCII Key-Value Configuration: |
|  | sys.ip=192.168.0.1\n           |               | sys.ip=192.168.0.1\n           |
|  | wifi.ssid=Tenda_5G\n ...       |               | wifi.ssid=Tenda_5G\n ...       |
|  | \x00 (Null Terminator)         |               | \x00 (Null Terminator)         |
|  +--------------------------------+               +--------------------------------+
|  | Padding: 0x00 / 0xFF to 64 KB  |               | Padding: 0x00 / 0xFF to 64 KB  |
|  +--------------------------------+               +--------------------------------+
|          [ACTIVE SECTOR]                                 [INACTIVE STANDBY]       |
|          (Mounted at boot:                                                        |
|           Valid CRC & Higher Seq)                                                 |
+-----------------------------------------------------------------------------------+
```

---

## 2. 8-Byte Binary Header Specification

Every CFM flash sector begins with a strict 8-byte binary header followed by the ASCII configuration stream:

| Byte Offset | Field Name | Data Type | Forensic Value in Dump | Functional Description |
|---|---|---|---|---|
| `0x00 - 0x03` | `crc32` | `uint32_le` | `0x34E8A155` (mtd5) / `0xCA5891A6` (mtd6) | IEEE 802.3 32-bit CRC calculated over all subsequent bytes `data[8:65536]`. |
| `0x04 - 0x07` | `seq_len` | `uint32_le` | `0x00000155` (341) / `0x00000154` (340) | Monotonically incrementing sequence / revision counter. |
| `0x08 - End` | `payload` | ASCII Stream | `<KEY>=<VALUE>\n...` | Newline-delimited configuration pairs, ending with `\x00`. |

### 2.1 The IEEE 802.3 CRC32 Verification Algorithm
In `libCfm.so` (`nvram_cfm_init_crc` at offset `0xD2BC`), the driver validates the integrity of the sector using standard polynomial `0xEDB88320`:

```c
// Decompiled CRC32 Verification Logic from libCfm.so:
int verify_cfm_sector(const uint8_t *sector_data) {
    uint32_t stored_crc = *(uint32_t *)(sector_data + 0);
    uint32_t stored_seq = *(uint32_t *)(sector_data + 4);

    // Calculate CRC32 starting from byte 8 across the remaining 65,528 bytes
    uint32_t calculated_crc = crc32(0, sector_data + 8, 65536 - 8);

    if (calculated_crc == stored_crc) {
        return 1; // Sector valid
    }
    return 0; // Sector corrupt
}
```

---

## 3. Wear Leveling & Power-Loss Recovery Mechanics

The ping-pong dual-sector architecture guarantees flash durability and atomicity:

### 3.1 Boot-Time Arbitration (`nvram_cfm_init` at `0xD208`)
1. At system startup, `cfmd` reads both `mtd5` and `mtd6`.
2. Computes the CRC32 of both sectors.
3. If both sectors have valid CRC32 checksums, `cfmd` compares their sequence counters (`seq_len`).
4. The sector with the **higher sequence counter** is mounted as the active system configuration (in our forensic dump, `mtd5` with `seq = 341` overrides `mtd6` with `seq = 340`).
5. If one sector is corrupted (e.g. from an interrupted write during power loss), `cfmd` automatically falls back to the valid standby sector and repairs the damaged bank.

### 3.2 Atomic Commit Pipeline (`nvram_cfm_commit` at `0xD8C0`)
When a user updates a configuration setting (e.g. changing Wi-Fi password):
1. The new configuration text is staged in a 64 KB DRAM buffer.
2. The sequence counter is incremented (`new_seq = active_seq + 1`).
3. The CRC32 is calculated across `buffer[8:65536]` and written into `buffer[0:3]`.
4. The buffer is written to the **standby sector** in flash.
5. Once SPI write verification confirms successful commit, the standby sector becomes active.
6. This ensures that even if power is abruptly disconnected mid-write, the existing active configuration remains 100% untouched.

---

## 4. Key Configuration Parameters Reference

The configuration payload is stored as plain ASCII lines: `<key>=<value>\n`. Below is a reference catalog of critical system variables:

| Configuration Key | Example Value | Subsystem Meaning & Impact |
|---|---|---|
| `lan.ip` | `192.168.0.1` | Router LAN Gateway IPv4 Address |
| `lan.mask` | `255.255.255.0` | Router LAN Subnet Mask |
| `wan.proto` | `dhcp` / `pppoe` | WAN Connection Mode |
| `wan.mac` | `50:0F:F5:00:00:01` | WAN Interface MAC Address (Cloned / Hardware) |
| `wl0.ssid` | `Tenda_5G` | 5 GHz Wireless Network Name |
| `wl0.wpa_psk` | `********` | 5 GHz WPA2 Pre-Shared Key |
| `wl1.ssid` | `Tenda_2.4G` | 2.4 GHz Wireless Network Name |
| `ucloud.syncserver` | `1` (Stock) / `0` (Opt) | Tenda Cloud Telemetry Agent Enable (`0` to disable) |
| `telnet.enable` | `0` (Stock) / `1` (Debug)| Embedded Root Telnet Console on TCP port 23 |
| `iptv.enable` | `1` (Stock) / `0` (Opt) | MultiWAN IPTV Bridge (`0` eliminates ghost ARP on WAN) |
| `sys.workmode` | `router` | Operating Mode (`router`, `ap`, `wisp`, `repeater`) |

---

## 5. Standalone Forensic Verification & Checksum Tool

To independently recalculate or modify CFM configuration files offline, the following Python script validates both sectors:

```python
import zlib, struct

def audit_cfm(filename):
    with open(filename, "rb") as f:
        data = f.read()
    assert len(data) == 65536, "Sector must be exactly 64 KB"
    
    stored_crc, seq = struct.unpack("<II", data[:8])
    calc_crc = zlib.crc32(data[8:]) & 0xFFFFFFFF
    
    print(f"File: {filename}")
    print(f"  Sequence: {seq}")
    print(f"  Stored CRC32:     {hex(stored_crc)}")
    print(f"  Calculated CRC32: {hex(calc_crc)}")
    if stored_crc == calc_crc:
        print("  Status: [PASS] Sector Valid")
    else:
        print("  Status: [FAIL] Checksum Mismatch")

# Audit dumped partitions:
audit_cfm("mtd5_cfm_primary.bin")
audit_cfm("mtd6_cfm_backup.bin")
```
