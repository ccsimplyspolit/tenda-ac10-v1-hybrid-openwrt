# Welcome to the Tenda AC10 V1.0 Engineering Wiki

> **Navigation:** [Wiki Portal](Home) | [Русскоязычный раздел (RU)](RU-Home)

The **Tenda AC10 V1.0** (FCC ID: `V7TAC10`, Model: `AC10`, Hardware Revision: `V1.0`) is a dual-band AC1200 gigabit Wi-Fi router based on the **Realtek RTL8197FS-VE5** System-on-Chip (SoC). While marketed as an entry-level consumer router, the underlying silicon combines a high-frequency MIPS core with advanced ASIC-level network acceleration and high-throughput 802.11ac Wave 2 wireless capabilities.

This technical wiki serves as the comprehensive, silicon-level reverse-engineering dossier and operating manual for the Tenda AC10 V1.0. It brings together years of community research from [4PDA Topic 885989](https://4pda.to/forum/index.php?showtopic=885989), independent binary deconstruction, and embedded systems engineering to provide complete transparency, recovery mechanisms, and two distinct production firmware solutions.

---

## Hardware Overview & Silicon Topology

The physical architecture of the Tenda AC10 V1.0 is engineered around a four-chipset topology:

```
+-----------------------------------------------------------------------------------+
|                        Tenda AC10 V1.0 System Architecture                        |
|                                                                                   |
|  +-------------------------+                     +-----------------------------+  |
|  |     MIPS 24KEc CPU      |  1.0 GHz / 64 KB L1 |      64 MB DDR2 SDRAM       |  |
|  | (Lexra RLX5281 Core)    |<===================>|   (System-in-Package SiP)   |  |
|  | 32 KB I-Cache / 32 KB D |   High-Speed Bus    |   0x00000000 - 0x04000000   |  |
|  +-------------------------+                     +-----------------------------+  |
|               |                                                 |                 |
|  +-----------------------------------------------------------------------------+  |
|  |                   Internal Multi-Layer Interconnect Matrix                  |  |
|  +-----------------------------------------------------------------------------+  |
|       |                     |                  |                     |            |
|       v                     v                  v                     v            |
|  +-------------+     +--------------+   +--------------+      +----------------+  |
|  | HW NAT ASIC |     | 2.4 GHz WLAN |   |  PCIe RC0    |      |  Gigabit MAC0  |  |
|  | Offload     |     | 2T2R 802.11n |   |  Gen 1.1 x1  |      |  RGMII (Port 6)|  |
|  | TLU Engine  |     | Baseband/MAC |   |  @0x18B00000 |      |  2.0 ns Rx Del |  |
|  +-------------+     +--------------+   +--------------+      +----------------+  |
|         |                   |                  |                     |            |
|         v                   v                  v                     v            |
|  ASIC SRAM NAPT        Skyworth RFE5    Realtek RTL8822BE     Realtek RTL8367RB   |
|  1024 5-Tuple Flows    2.4 GHz Front    5 GHz 802.11ac Card   5-Port GbE Switch   |
|  940 Mbps Line-Rate    2x Dipole Ant    2x Dipole Ant         SMI: GPIO 18/19/58  |
|  0.0% CPU Overhead     (HT40 300 Mbps)  (Blank eFuse 0xFF)    Port 3: WAN (RJ45)  |
|                                         (VHT80 866.7 Mbps)    Ports 0-2: LAN (RJ45|
+-----------------------------------------------------------------------------------+
```

### Verified Hardware Specifications

> **Notice on 4PDA Hardware Misconceptions**: Factory packaging and early forum posts frequently reported 16 MB SPI Flash and 128 MB RAM. Hardware inspections and memory dumps establish conclusively that **all retail AC10 V1.0 units feature 8 MB SPI NOR Flash and 64 MB DDR2 SDRAM**.

- **Main Processor (SoC)**: Realtek RTL8197FS-VE5 (32-bit MIPS 24KEc @ 1.0 GHz, Little-Endian `mipsel`).
- **Embedded Memory**: 64 MB (512 Mbit) DDR2 SDRAM co-packaged inside the SoC package (SiP).
- **SPI NOR Flash**: 8 MB (8,388,608 bytes) Winbond W25Q64FV / W25Q64JV (`0xEF4017`).
- **2.4 GHz Radio**: Integrated RTL8197FS WiSoC MAC/Baseband (2T2R 802.11b/g/n, up to 300 Mbps PHY rate) paired with Skyworth RFE Type 5 front-end modules.
- **5 GHz Radio**: Realtek RTL8822BE on PCIe Root Complex 0 (2T2R 802.11a/n/ac Wave 2, up to 866.7 Mbps PHY rate) paired with Skyworth RFE Type 6 front-end modules and unburned physical eFuse (`0xFF`).
- **Ethernet Switch**: Realtek RTL8367RB-VB 5-port Gigabit Switch connected via RGMII on Port 6 and controlled via SMI bit-banging (MDC: GPIO 18, MDIO: GPIO 19, Reset: GPIO 58).

---

## Key Achievements & Engineering Breakthroughs

1. **Wire-Speed Hardware NAT Offload (940 Mbps at 0.0% CPU)**:
   - Re-engineered the Realtek ASIC Table Lookup Unit (TLU) and NAPT engine (`rtl819x_hwnat.c`).
   - Fixed historical host-numeric byte ordering bugs that caused packet dropouts on non-vendor kernel trees.
   - Provides full 940 Mbps bidirectional throughput on gigabit WAN connections with negligible CPU utilization.

2. **Full-Speed 802.11ac Wave 2 Wi-Fi (866.7 Mbps Physical Link)**:
   - Solved the unburned physical eFuse dilemma (`0xFF` reading) on the RTL8822BE PCIe card by synthesizing a dynamic calibration injector (`set-mib.sh`).
   - Re-aligned crystal capacitive loading (`XCAP=27`) and power tracking bias matrices to ensure stable RF output across both 2.4 GHz and 5 GHz bands.

3. **Complete Elimination of Telemetry & Backdoors**:
   - Deconstructed and neutralized `/bin/ucloud_v2`, China cloud reporting daemons, and aggressive `/bin/sntp` broadcast retry loops.
   - Closed unauthenticated management interfaces (`/cgi-bin/DownloadFlash`) that permitted full flash downloads over local networks.
   - Eliminated vulnerabilities associated with `CVE-2026-11405` by migrating management services to hardened OpenWrt daemons (`uhttpd`, `rpcd`).

4. **100% Offline Autonomous Disaster Recovery**:
   - Disassembled the Realtek Stage 2 Booter (`booter_stage2_v3.4.11B.9`) to isolate its emergency TFTP recovery mechanism.
   - Engineered a standalone Python disaster recovery suite (`tools/autonomous_recovery/`) capable of unbricking any corrupted router over standard ethernet in under 3 minutes without UART or JTAG hardware.

---

## Two Production Firmware Tracks

This project provides two distinct, fully validated tracks to meet different user requirements:

| Operational Feature | Track 1: Stock+ Optimized Firmware | Track 2: Hybrid OpenWrt 4.14 Port |
|---|---|---|
| **Base Kernel** | Linux 3.10.90 (Vendor BSP) | Linux 4.14.221 (LTS OpenWrt Target) |
| **System Environment** | Vendor `/bin/httpd` + `/bin/cfm` | OpenWrt 19.07 (`musl` libc, LuCI Web UI, SSH) |
| **WAN-LAN IPv4 Throughput** | **941 Mbps** (HWNAT Active, 0.0% CPU) | **940 Mbps** (`rtl819x_hwnat` Active, 0.5% CPU) |
| **Software-Only NAT Speed** | 140 Mbps (100% CPU bottleneck) | 450–520 Mbps (100% CPU bottleneck) |
| **5 GHz 802.11ac Real-World Rate**| Up to 580 Mbps TCP (`iperf3`) | Up to 595 Mbps TCP (`iperf3`) |
| **Background Telemetry** | **100% Disabled & Purged** | **Completely Absent** |
| **Ghost Bridge (`br2`)** | **Disabled** (Reclaimed resources) | **Non-Existent (Clean swconfig)** |
| **Max Concurrent Connections** | 8,192 states (`sys.maxconn=8192`) | 16,384 states (Dynamic memory sizing) |
| **Wi-Fi uTP / Torrent Fix** | Applied (`manual_edca=1`, `disable_txsc=1`)| Integrated in driver profile |
| **Extensibility & Packages** | Fixed ROM (Vendor features only) | Full `opkg` ecosystem (WireGuard, Adblock, etc.) |
| **Target User** | Users seeking stock simplicity without bugs | Enthusiasts requiring VPN, advanced routing, LuCI |

---

## Documentation Roadmap

Explore the comprehensive sections of this wiki:

1. **[Hardware Architecture](EN-Hardware-Architecture)**: Comprehensive analysis of the RTL8197FS silicon, MIPS memory map, RTL8822BE PCIe calibration, RTL8367RB SMI switch protocol, and Winbond 8 MB SPI NOR flash partitioning.
2. **[Binary Reverse Engineering](EN-Binary-Reverse-Engineering)**: Step-by-step disassembly of Realtek Booter v3.4.11B.9, the 16-byte `cr6c` kernel container, `rtl8192cd` MIB table structures, the HWNAT ASIC TLU engine, and Unicorn 2.1.4 firmware validation proofs.
3. **[Stock+ Optimization Guide](EN-Stock-Plus-Optimization)**: Detailed forensic audit of vendor firmware vulnerabilities, memory bloat deconstruction, the uTP/torrent stability fix, and deployment of `RouterCfm_optimized_sanitized.cfg`.
4. **[Hybrid OpenWrt 4.14 Port](EN-Hybrid-OpenWrt-4.14-Port)**: Target architecture, verified Device Tree Source (`tenda-ac10-v1.dts`), monolithic wireless driver integration, dynamic calibration injection (`set-mib.sh`), and `CVE-2026-11405` mitigation.
5. **[Offline TFTP Recovery Guide](EN-Offline-TFTP-Recovery-Guide)**: Emergency unbricking playbook, analysis of bootloader network invariants (ICMP drop, WAN port isolation), and execution guide for the autonomous Python recovery suite.
6. **[FAQ & Troubleshooting](EN-FAQ-and-Troubleshooting)**: In-depth answers to common 4PDA community questions, AC10 V3.0 (eCos RTOS) incompatibility, Cudy WR1500 notes, Web UI upgrade error codes, and optimal 5 GHz channel configurations.

---

## Quick Start Summary

- **To deploy Stock+**: Upload [`config/RouterCfm_optimized_sanitized.cfg`](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/blob/main/config/RouterCfm_optimized_sanitized.cfg) via the vendor Web UI under **Administration** -> **Backup/Restore**. Default credentials become `admin`/`admin`.
- **To deploy Hybrid OpenWrt 4.14 via Web UI**: Flash `tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin` via **Administration** -> **Firmware Upgrade**.
- **To recover from a brick**: Connect your PC to **LAN Port 1**, run `tools/autonomous_recovery/run_emergency_recovery.bat`, and power on the router while holding **RST/WPS for 15 seconds**.

---

## Community Heritage & Acknowledgments

This documentation is dedicated to the independent engineers and enthusiasts of the **4PDA Tenda AC10 Community** ([Topic 885989](https://4pda.to/forum/index.php?showtopic=885989)), specifically:
- **`vladisslav0`**: Pioneer of RTL8197FS OpenWrt development, creator of the original 3.18 kernel port, and identifier of the `rtl8192cd` MIB table parameters.
- **`ParAAvis` / `Parav1s`**: Documented the fundamental 15-second reset disaster recovery method for Realtek Booter v3.4.11B.9.
- **`sorine` & `AndrewWhite3620`**: Advanced custom OpenWrt kernel trees and package backports for Realtek MIPS architectures.
- **`RusselMorroz` & `Dan911`**: Provided verified programmer dumps and mapped the factory calibration eFuse and MAC offset tables.
- **DeepInvestigator & Teamwork Contributors**: Completed the Stage 2 booter disassembly, AutoBurn `$s7` bug discovery, Unicorn 2.1.4 emulation suite, and autonomous Python recovery tooling.
