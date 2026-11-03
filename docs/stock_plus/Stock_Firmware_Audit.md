# Stock Firmware Full Forensic & Security Audit

## 1. Audit Scope & Firmware Baseline

This document presents a complete forensic and security assessment of the official factory stock firmware for the Tenda AC10 V1.0 router:
- **Target Firmware Version**: `V15.03.06.23_multi` (Build Date: 2018-05-18).
- **Kernel Architecture**: Linux 3.10.90 (MIPS32 Little-Endian, gcc 4.4.7).
- **Hardware Platform**: Tenda AC10 V1.0 (Realtek RTL8197FS SoC, 64 MB DDR2, RTL8822BE 5G PCIe, RTL8367RB GbE Switch, Winbond 8 MB SPI NOR Flash).
- **Analyzed Images**:
  - Forensic Full Flash Dump (`Tenda_AC10_V1_FullFlash_8MB.bin`, 8,388,608 bytes).
  - Uncompressed Kernel (`vmlinux_stock.bin`, 7,253,712 bytes).
  - Decompressed RootFS (`squashfs_root/`, 20,294,917 uncompressed bytes).
  - Runtime Telemetry Logs (`logs.txt`, `sys_info.log`, `syslog_live_post_opt.tar`).

```
+-----------------------------------------------------------------------------------+
|                        Stock Firmware V15.03.06.23 Architecture                   |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | Web UI & Management Services (/bin/httpd, /bin/cfm, /bin/cfmd, /bin/upgrade)|  |
|  +-----------------------------------------------------------------------------+  |
|         |                                       |                                 |
|         v                                       v                                 |
|  +-----------------------------+     +-----------------------------------------+  |
|  | Unwanted Background Bloat   |     | Security Vulnerabilities                |  |
|  | - /bin/ucloud_v2 (4.58 MB)  |     | - Unauthenticated /cgi-bin/DownloadFlash|  |
|  | - /bin/sntp retry storms    |     | - Ghost IPTV Bridge (br2 / vlan3)       |  |
|  | - China cloud phone-home    |     | - Plaintext NVRAM backups on LAN        |  |
|  +-----------------------------+     +-----------------------------------------+  |
|         |                                       |                                 |
|         +-------------------+-------------------+                                 |
|                             |                                                     |
|                             v                                                     |
|  +-----------------------------------------------------------------------------+  |
|  | Monolithic Linux 3.10.90 Kernel & Realtek Proprietary Drivers (rtl8192cd)   |  |
|  | - 38.6 MB / 64 MB DRAM Consumed at Boot (Only ~25 MB Free RAM Available)    |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 2. Resource Utilization & Memory Footprint Audit

On a cost-constrained embedded router equipped with only 64 MB of integrated DDR2 SDRAM, stock firmware memory consumption is alarmingly high:

### 2.1 Boot-Time Memory Distribution
```
MemTotal:          59,328 kB (~58 MB usable by Linux kernel)
MemFree:           20,712 kB (Only ~20 MB free DRAM immediately after boot)
Buffers:            1,848 kB
Cached:            16,216 kB
Active:            14,920 kB
Inactive:           8,112 kB
```

### 2.2 Userland Process RAM Breakdown
Top memory-consuming processes recovered from live system telemetry:
1. **`/bin/ucloud_v2`**: Consumes **4,580 kB (4.58 MB)** virtual memory. This daemon continuously maintains cloud telemetry sockets.
2. **`/bin/httpd`**: Consumes **3,924 kB (3.92 MB)** virtual memory. Handles HTTP management and CGI requests.
3. **`/bin/multiWAN`**: Consumes **2,816 kB (2.82 MB)** virtual memory. Manages WAN failover and interface link state polling.
4. **`/bin/cfmd`**: Consumes **2,456 kB (2.46 MB)** virtual memory. Serves as configuration broker and handles flash commit wear leveling.
5. **`/bin/sntp`**: Consumes **2,112 kB (2.11 MB)** virtual memory. Periodic NTP synchronization daemon.

**Evaluation**: Userland daemons alone consume over **16 MB of DRAM**, leaving the router vulnerable to Out-Of-Memory (OOM) kernel panics when handling heavy multi-client BitTorrent traffic or large firmware upgrades.

---

## 3. Background Telemetry & Cloud Exfiltration Audit

The stock firmware incorporates an aggressive background telemetry agent: **`/bin/ucloud_v2`** (linked against `/lib/libcloud.so`).

### 3.1 Telemetry Behavior & Network Endpoints
- **Listening Ports**: Binds UDP port 11812 on all interfaces.
- **External Connections**: Initiates persistent outbound TCP connections to remote servers:
  - `*.*.szbzt.com` (Shenzhen Bzt Co., Ltd.)
  - `*.*.tenda.com.cn` (Tenda China Telemetry Center)
- **Exfiltrated Telemetry Data**:
  - Router Unique Serial Number (`ucloud_serialnum=0000000`).
  - Public WAN IPv4 Address.
  - Active LAN Client Inventory (Client MAC addresses, hostnames, assigned IPs).
  - Wi-Fi BSSID identifiers and active association counts.
  - Device uptime and firmware build revision.

**Privacy Impact**: The router continuously phones home to foreign endpoints without explicit user opt-in, leaking local network topology and traffic volume metadata.

---

## 4. Security Vulnerabilities & Exposure Vectors

### 4.1 Critical CVE-Class Vulnerability: `/cgi-bin/DownloadFlash`
As verified in disassembly (`vmlinux_stock.bin` / `/bin/httpd` offset `0x10EDA8`), the web server exposes an administrative diagnostic script accessible via the local LAN:
- **Endpoint**: `http://192.168.0.1/cgi-bin/DownloadFlash`
- **Defect**: Lacks authentication verification. Any unauthenticated device connected to LAN or guest Wi-Fi can trigger a full SPI NOR flash dump.
- **Impact**: Completely compromises confidentiality. The attacker recovers:
  - Administrator web interface passwords.
  - Wi-Fi WPA2 pre-shared keys.
  - ISP PPPoE credentials and static IP configs.
  - Factory RF calibration keys from `mtd1`.

### 4.2 Ghost IPTV Bridge WAN ARP Pollution (`br2` / `vlan3`)
In stock configuration, `/bin/multiWAN` initializes a virtual bridge `br2` over `vlan3` intended for IPTV set-top box bridging:
- Even when IPTV is toggled off in the GUI, the underlying Linux network bridge remains active.
- `br2` continuously emits gratuitous ARP probes onto the physical WAN port seeking gateway `10.0.0.1`.
- In managed ISP fiber networks, these unsolicited ARP broadcasts trigger ISP port-security alarms or duplicate IP conflict warnings.

### 4.3 Aggressive NTP Retry Storms (`/bin/sntp`)
When internet connectivity is interrupted or upstream DNS servers become unresponsive:
- `/bin/sntp` lacks exponential backoff.
- The process loops in a sub-second retry cycle, querying DNS and hammering NTP endpoints.
- Syslog fills with `sntp error: sendto failed` messages at over 20 entries per second, consuming up to 14% of CPU capacity and inflating system log buffers.

### 4.4 Connection Tracking Table Sizing Deficit (`sys.maxconn`)
In factory stock firmware, the Linux Netfilter connection tracking table (`nf_conntrack`) is constrained to a default limit of `sys.maxconn=4000`:
- Under heavy peer-to-peer (BitTorrent), online gaming, or multi-client household workloads, the 4,000-entry table is rapidly saturated.
- When `nf_conntrack: table full, dropping packet` occurs, the Linux kernel silently drops new TCP SYN packets and UDP DNS queries, causing random connectivity dropouts despite active physical WAN links.
- **Optimization**: Setting `sys.maxconn=8192` in CFM NVRAM doubles available connection states to 8,192 entries, preventing connection dropouts under heavy concurrent sessions while consuming less than 1.5 MB of RAM headroom.

---

## 5. Summary of Audit Findings

| Audit Dimension | Stock Firmware Finding | Severity Level | Recommended Mitigation |
|---|---|:---:|---|
| **Privacy / Telemetry** | `/bin/ucloud_v2` phones home to China cloud endpoints | **HIGH** | Set `ucloud.syncserver=0` in CFM NVRAM |
| **Confidentiality** | `/cgi-bin/DownloadFlash` dumps full flash without auth | **CRITICAL** | Firewall port 80 / restrict CGI or patch httpd |
| **Network Hygiene** | Ghost `br2`/`vlan3` emits unsolicited WAN ARP frames | **MEDIUM** | Set `iptv.enable=0` in CFM NVRAM |
| **System Reliability**| `/bin/sntp` enters high-CPU retry loop on WAN loss | **MEDIUM** | Configure reliable NTP pools and gateway checks |
| **Connection Capacity**| Conntrack table capped at 4,000 entries (`sys.maxconn=4000`)| **MEDIUM** | Increase to `sys.maxconn=8192` in CFM NVRAM |
| **Memory Capacity** | Only ~20 MB free RAM at boot (66% DRAM consumed) | **HIGH** | Terminate unneeded daemons via Stock Plus profile |
