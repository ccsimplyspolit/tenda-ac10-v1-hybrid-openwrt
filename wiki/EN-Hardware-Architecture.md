# Tenda AC10 V1.0 Hardware Architecture & Silicon Dossier

> **Section:** [Home (EN)](EN-Home) | [Russian Version](RU-Hardware-Architecture) | [Wiki Portal](Home)

This document provides a comprehensive hardware architecture specification and silicon-level teardown of the **Tenda AC10 V1.0** (FCC ID: `V7TAC10`). It details the System-on-Chip (SoC) microarchitecture, memory map, peripheral interconnects, wireless radio calibration pipelines, switch management interfaces, and SPI NOR flash layout.

---

## 1. Executive Silicon & Topology Overview

The Tenda AC10 V1.0 is engineered around an integrated four-chipset architecture:
1. **Core Processing & 2.4G WLAN**: Realtek RTL8197FS-VE5 (MIPS 24KEc @ 1.0 GHz + 64 MB DDR2 SiP + 2.4 GHz 802.11b/g/n 2T2R WiSoC).
2. **5 GHz 802.11ac WLAN**: Realtek RTL8822BE (PCIe Gen 1.1 x1, 802.11ac Wave 2 2T2R, VHT80 866.7 Mbps).
3. **Gigabit Switch Core**: Realtek RTL8367RB-VB (5-Port 10/100/1000M Gigabit switch with RGMII CPU uplink).
4. **Non-Volatile Storage**: Winbond W25Q64FV / W25Q64JV (8 MB Serial Peripheral Interface NOR Flash).

```
+-----------------------------------------------------------------------------------+
|                        Tenda AC10 V1.0 Silicon Topology                           |
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

---

## 2. Realtek RTL8197FS-VE5 SoC Deep Dive

The **RTL8197FS-VE5** is an integrated System-on-Chip packaged in a 216-pin Thin Fine-Pitch Ball Grid Array (TFBGA). It incorporates a 32-bit MIPS CPU core and embedded DRAM inside a single Multi-Chip Package (MCP / SiP).

### 2.1 CPU Microarchitecture
- **Core Type**: MIPS 24KEc (Lexra RLX5281 instruction-compatible core).
- **Instruction Set**: MIPS32 Release 2, Little-Endian (`mipsel`).
- **Core Clock Frequency**: 1.0 GHz (1000 MHz nominal PLL clock).
- **L1 Cache Hierarchy**:
  - 32 KB 4-way set-associative Instruction Cache (32-byte cache line size).
  - 32 KB 4-way set-associative Data Cache (write-back, 32-byte cache line size).
- **Coprocessor 0 (CP0)**: Standard MIPS CP0 register set featuring Count/Compare cycle timers, software interrupt triggers, and TLB management.

### 2.2 System-in-Package (SiP) DDR2 SDRAM
The RTL8197FS eliminates external memory traces on the motherboard by integrating high-density DDR2 SDRAM directly into the chip substrate:
- **Capacity**: 64 MB (512 Mbit / 67,108,864 bytes).
- **Bus Width**: 16-bit DDR2 interface operating at 400 MHz (DDR2-800 equivalent).
- **Physical Address Window**: `0x00000000` to `0x03FFFFFF`.
- **Memory Controller Registers**: Base physical address `0x18001000` (accessed via KSEG1 uncached base at `0xB8001000`).

### 2.3 MIPS32 Memory Segmentation & Virtual Address Map
The MIPS 24KEc MMU operates across four standard execution segments:

| Virtual Segment | Address Range | Physical Mapping | Cache Policy | Typical Runtime Usage |
|---|---|---|---|---|
| **KUSEG** | `0x00000000 - 0x7FFFFFFF` | MMU / TLB Translated | Cached | Userland processes (`/bin/httpd`, `uhttpd`, `cfm`) |
| **KSEG0** | `0x80000000 - 0x9FFFFFFF` | Physical `0x00000000 - 0x1FFFFFFF` | Direct Mapped, Cached | Linux kernel code, kernel data, Booter Stage 2 |
| **KSEG1** | `0xA0000000 - 0xBFFFFFFF` | Physical `0x00000000 - 0x1FFFFFFF` | Direct Mapped, Uncached | Memory-Mapped I/O (MMIO), DMA buffers, Boot SPI |
| **KSEG2/3**| `0xC0000000 - 0xFFFFFFFF` | MMU / TLB Translated | Cached | Kernel `vmalloc` space, loadable modules |

### 2.4 Physical MMIO Peripheral Registers
All on-chip peripheral control registers are mapped starting at physical base `0x18000000` (accessed through uncached KSEG1 at `0xB8000000`):

| Peripheral Subsystem | Physical Address Range | KSEG1 Uncached Address | Operational Purpose |
|---|---|---|---|
| **System Control & PLL** | `0x18000000 - 0x180000FF` | `0xB8000000 - 0xB80000FF` | Chip ID, clock gating, soft reset registers |
| **DDR2 Memory Controller**| `0x18001000 - 0x18001FFF` | `0xB8001000 - 0xB8001FFF` | SDRAM timing, refresh rate, PHY calibration |
| **UART 0 / UART 1** | `0x18002000 - 0x18002FFF` | `0xB8002000 - 0xB8002FFF` | NS16550A serial consoles (38400 baud default) |
| **Hardware Timer & WDT** | `0x18003000 - 0x18003FFF` | `0xB8003000 - 0xB8003FFF` | System timers, hardware watchdog timer control |
| **GPIO Controller (Bank 0)**| `0x18003500 - 0x180035FF` | `0xB8003500 - 0xB80035FF` | GPIO pins 0..31 direction and data registers |
| **GPIO Controller (Bank 1)**| `0x18003600 - 0x180036FF` | `0xB8003600 - 0xB80036FF` | GPIO pins 32..63 direction and data registers |
| **SPI Flash Controller** | `0x18004000 - 0x18004FFF` | `0xB8004000 - 0xB8004FFF` | High-speed NOR flash read/write commands |
| **Gigabit MAC 0 (GMAC0)** | `0x18005000 - 0x18007FFF` | `0xB8005000 - 0xB8007FFF` | Ethernet MAC, DMA descriptor rings, RGMII |
| **HW NAT Engine (TLU)** | `0x18004400 - 0x180047FF` | `0xBB804400 - 0xBB8047FF` | Table Lookup Unit, ASIC NAPT flow SRAM |
| **Internal 2.4G WLAN MAC** | `0x18640000 - 0x1864FFFF` | `0xB8640000 - 0xB864FFFF` | 802.11b/g/n Baseband and MAC registers |
| **PCIe Root Complex 0** | `0x18B00000 - 0x18B0FFFF` | `0xB8B00000 - 0xB8B0FFFF` | PCIe Gen 1.1 configuration space and MMIO |

---

## 3. Realtek RTL8822BE 5 GHz PCIe Wireless Subsystem

High-speed 5 GHz wireless networking is powered by an independent **Realtek RTL8822BE** wireless network card interfaced via PCIe:
- **Interconnect**: PCI Express Base Specification 1.1 Root Complex 0 (`RC0` @ `0x18B00000`).
- **PCI Device Identification**: Vendor ID `0x10EC` (Realtek Semiconductor), Device ID `0xB822` (RTL8822BE 802.11ac PCIe Wireless Network Adapter).
- **Bus Topology**: Subsystem PCI ID `10EC:B822`, Bus 0, Device 0, Function 0. Interfaced to SoC via physical interrupt line **IRQ 5**.
- **Radio Specifications**:
  - IEEE 802.11a/n/ac Wave 2 compliant.
  - 2T2R (2 Transmit, 2 Receive) MIMO spatial streams.
  - Channel Bandwidth: 20 MHz, 40 MHz, and 80 MHz (VHT80).
  - Modulation: Up to 256-QAM (MCS 0..9).
  - Maximum Physical PHY Rate: **866.7 Mbps** (at 80 MHz, 400 ns short guard interval).
- **RF Front-End**: Skyworth RFE Type 6 module incorporating external high-power Power Amplifiers (PA) and Low-Noise Amplifiers (LNA).

### 3.1 The Blank Physical eFuse Dilemma (`0xFF`)
Forensic analysis of the RTL8822BE card on retail AC10 V1.0 routers revealed that the on-die physical eFuse array is completely unprogrammed:
- Every byte of the hardware eFuse returns `0xFF`.
- When initialized by standard upstream Linux drivers, the card fails with `halmac_parse_efuse_data_88xx: error code 5 (invalid eFuse header)`.
- **Engineering Solution**: In the Tenda architecture, the vendor stores factory calibration data inside an SPI flash partition labeled `CFG` (`mtd2` at offset `0x00020000`). The wireless driver (`rtl8192cd`) must read this flash sector, reconstruct the 524-entry MIB table (`MIB_TABLE`), and inject parameters dynamically using `/bin/set-mib.sh` or private ioctls (`SIOCDEVPRIVATE 0x89f1`).

### 3.2 Crystal Oscillator Capacitive Tuning (`XCAP=27`)
RF frequency alignment requires precise tuning of the 40 MHz reference crystal:
- **Register**: `0x002C` on the RTL8822BE baseband controller.
- **Factory Setting**: Value `0x1B` (27 decimal).
- Incorrect crystal load capacitance causes central frequency offset drift, leading to degraded 5 GHz range, high packet error rates (PER), and client negotiation failures at VHT80.

---

## 4. Realtek RTL8367RB-VB Gigabit Switch Subsystem

The Tenda AC10 V1.0 incorporates a dedicated **Realtek RTL8367RB-VB** 5-Port 10/100/1000M Gigabit Ethernet switch controller.

### 4.1 Physical Port Mapping & VLAN Architecture
The switch routes traffic across four external RJ45 jacks and an internal CPU RGMII link:

```
+-----------------------------------------------------------------------------------+
|                        RTL8367RB-VB Port Mapping & VLANs                          |
|                                                                                   |
|  Physical Port 3 (WAN RJ45) ------> Port 3 Switch Core ----> VLAN 2 (Tagged)      |
|                                                                     |             |
|  Physical Port 0 (LAN 1 RJ45) ----> Port 0 Switch Core ----+        |             |
|  Physical Port 1 (LAN 2 RJ45) ----> Port 1 Switch Core ----+-> VLAN 1 (Tagged)   |
|  Physical Port 2 (LAN 3 RJ45) ----> Port 2 Switch Core ----+        |             |
|                                                                     v             |
|  Internal CPU GMAC0 <============== Port 6 RGMII Bus <==============+             |
|  (2.0 ns Rx Delay)                  (Realtek 4-Byte CPU Header)                   |
+-----------------------------------------------------------------------------------+
```

- **Physical Port 3**: Dedicated external WAN interface (labeled "WAN" on enclosure).
- **Physical Ports 0, 1, 2**: External LAN interfaces (labeled "LAN 1", "LAN 2", "LAN 3").
- **Internal Port 6**: RGMII (Reduced Gigabit Media Independent Interface) connected to the RTL8197FS GMAC0 controller. Operates with an RX internal delay of **2.0 nanoseconds** (`rx-internal-delay-ps = <2000>`) to compensate for PCB trace propagation skew.

### 4.2 SMI Bus Bit-Banging & Reset GPIO Mapping
The switch lacks a hardware MDIO bus master on the SoC. The Linux kernel communicates with the RTL8367RB internal registers using a Serial Management Interface (SMI) bit-banging protocol over general-purpose I/O pins:
- **SMI Clock (`MDC`)**: Connected to **GPIO 18**.
- **SMI Data (`MDIO`)**: Connected to **GPIO 19**.
- **Switch Hardware Reset (`RST`)**: Connected to **GPIO 58** (active-low).

#### The GPIO 58 Kernel Trap in Linux DTS
The RTL8197FS GPIO controller divides pins across 32-bit register banks:
- **Bank 0 (`gpio0`)**: GPIO 0 through GPIO 31 (`PABCD_DAT` @ `0xB8003500`).
- **Bank 1 (`gpio1`)**: GPIO 32 through GPIO 63 (`PEFGH_DAT` @ `0xB8003600`).

GPIO 58 belongs to Bank 1, specifically bit 26 of `PEFGH_DAT` (Bank H2, `58 - 32 = 26`). Specifying `<&gpio0 58>` in a Device Tree causes the Linux kernel GPIO driver to write out of bounds, resulting in immediate kernel panic during boot. The **only** valid Device Tree binding is:

```dts
realtek,smi-reset-gpio = <&gpio1 26 GPIO_ACTIVE_LOW>;
```

---

## 5. Winbond W25Q64 8 MB SPI NOR Flash Memory Map

The non-volatile storage is an 8 MB (64 Mbit) Winbond SPI NOR flash memory chip:
- **Model**: Winbond W25Q64FVSSIG / W25Q64JVSSIQ (or compatible GigaDevice GD25Q64C).
- **JEDEC ID**: `0xEF 0x40 0x17` (Winbond W25Q64).
- **Total Capacity**: 8,388,608 bytes (8 MB).
- **Erase Geometry**: 128 uniform blocks of 64 KB (`0x10000` bytes) each.
- **Clock Speed**: Driven by the RTL8197FS SPI controller at **41.67 MHz** in Fast Read Dual-Output mode.

### Forensic Partition Geometry

Every partition boundary has been extracted from the forensic master dump (`Tenda_AC10_V1_FullFlash_8MB.bin`) and validated:

```
+---------------------------------------------------------------------------------------+
|                 Tenda AC10 V1.0 8 MB (8,388,608 Bytes) SPI Flash Memory Map            |
+---------------------+-------------------+---------------------+-----------------------+
| Offset Range (Hex)  | Partition Name    | Size (Bytes / KB)   | Content Description   |
+---------------------+-------------------+---------------------+-----------------------+
| 0x000000 - 0x020000 | mtd1: Bootloader  |   131,072 (128 KB)  | Stage 1 & Stage 2     |
+---------------------+-------------------+---------------------+-----------------------+
| 0x020000 - 0x030000 | mtd2: CFG (Cal)   |    65,536 (64 KB)   | 40 RF Factory Keys    |
+---------------------+-------------------+---------------------+-----------------------+
| 0x030000 - 0x23BC12 | Kernel (cr6c)     | 2,145,298 (~2.1 MB) | Linux 3.10.90 Kernel  |
+---------------------+-------------------+---------------------+-----------------------+
| 0x23BC12 - 0x76CC14 | RootFS (hsqs)     | 5,443,586 (~5.4 MB) | SquashFS 4.0 Tenda-XZ |
+---------------------+-------------------+---------------------+-----------------------+
| 0x76CC14 - 0x7E0000 | Dirty JFFS2 Gap   |   472,044 (461 KB)  | Manufacturing Residue |
+---------------------+-------------------+---------------------+-----------------------+
| 0x7E0000 - 0x7F0000 | mtd5: CFM Primary |    65,536 (64 KB)   | Primary NVRAM Sector  |
+---------------------+-------------------+---------------------+-----------------------+
| 0x7F0000 - 0x800000 | mtd6: CFM Backup  |    65,536 (64 KB)   | Backup NVRAM Sector   |
+---------------------+-------------------+---------------------+-----------------------+
| 0x030000 - 0x7E0000 | mtd3: KernelFS    | 8,060,928 (7,872 KB)| Total Firmware Slot   |
+---------------------+-------------------+---------------------+-----------------------+
| 0x030000 - 0x76CC14 | Stock Recovery    | 7,588,884 (7,411 KB)| Clean TFTP Image      |
+---------------------+-------------------+---------------------+-----------------------+
```

### Forensic Checksum Verification Table

| Partition Index | Stock Runtime Label | OpenWrt DTS Label | Flash Start | Flash End | Byte Count | SHA-256 Checksum |
|---|---|---|---|---|---:|---|
| **mtd0** | `ALL` | *(Full Flash)* | `0x00000000` | `0x00800000` | `8,388,608` | `af40888b2a92539ef51218a7ed6dc25c48ac2cd51950ffcf25bec44b98252833` |
| **mtd1** | `Bootloader` | `bootloader` | `0x00000000` | `0x00020000` | `131,072` | `5f351f3bbcfa3a1b2a5f17bdcdd5191deec5685126bb0a5830f96788d8962036` |
| **mtd2** | `CFG` | `calibration` | `0x00020000` | `0x00030000` | `65,536` | `2b0224aff5c250bf10c25d94c38a638496543cc2af1287a692c58855e269aba7` |
| **mtd3** | `KernelFS` | `firmware` | `0x00030000` | `0x007E0000` | `8,060,928` | `4679fa4673696318288896d6518515db7c0db4e5defb88d8bfe552bc98181c45` |
| **Slice** | *(Kernel)* | *(Kernel)* | `0x00030000` | `0x0023BC12` | `2,145,298` | `023bc89c65c7c0c00ee6ca34b65c07644c3df62f3c38e76e760bcef54248dd33` |
| **Slice** | `SquashFS` | *(RootFS)* | `0x0023BC12` | `0x0076CC14` | `5,443,586` | `fcbf377debd9ab7d819c186c15660a65d5a32b579310f758d2c764505f728749` |
| **Gap** | `Dirty JFFS2`| *(Writable)* | `0x0076CC14` | `0x007E0000` | `472,044` | *(Factory test artifacts and dirty blocks)* |
| **mtd5** | `CFM` | `cfm_primary`| `0x007E0000` | `0x007F0000` | `65,536` | `289e4321ec0c5b656c9f5e57c56279846387dbcd4b8cab1f89d843fb04faa457` |
| **mtd6** | `CFM_BACKUP`| `cfm_backup` | `0x007F0000` | `0x00800000` | `65,536` | `26bfb1cd0995670092040bf550adaef538f8bbe8590f7e2dfc0e7153acdc1564` |
| **Image** | `Stock Recov`| *(TFTP)* | `0x00030000` | `0x0076CC14` | `7,588,884` | `a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa` |

---

## 6. Verified GPIO Pinout, Diagnostic Pinouts, & MAC Architecture

### 6.1 Complete Silicon GPIO Pinout Mapping
Through low-level register tracing and hardware deconstruction, the complete GPIO pinout of the RTL8197FS on the Tenda AC10 V1.0 board has been verified:

| Physical GPIO Pin | Linux DTS Binding | Active Level | Direction | Hardware Function & Interconnect |
|---|---|---|---|---|
| **GPIO 18** | `<&gpio0 18>` | N/A | Output | RTL8367RB Gigabit Switch SMI Management Clock (`MDC`) |
| **GPIO 19** | `<&gpio0 19>` | N/A | Bi-dir | RTL8367RB Gigabit Switch SMI Management Data (`MDIO`) |
| **GPIO 33** | `<&gpio1 1 GPIO_ACTIVE_LOW>` | Active-Low | Output | WPS Status LED |
| **GPIO 54** | `<&gpio1 22 GPIO_ACTIVE_LOW>`| Active-Low | Input | Hardware Reset Push Button (pull-up) |
| **GPIO 56** | `<&gpio1 24 GPIO_ACTIVE_LOW>`| Active-Low | Input | Wi-Fi / WPS Push Button (pull-up) |
| **GPIO 57** | `<&gpio1 25 GPIO_ACTIVE_LOW>`| Active-Low | Output | System Status / Power LED (`SYS`) |
| **GPIO 58** | `<&gpio1 26 GPIO_ACTIVE_LOW>`| Active-Low | Output | RTL8367RB Gigabit Switch Hardware Reset (`RST`) |
| **GPIO 59..60** | Internal Multiplexing | N/A | I/O | UART0 serial transceiver / JTAG debug interface |
| **GPIO 61** | Pinmux Control | N/A | System | SPI NOR Flash / GPIO multiplexer control |

> **Critical Silicon Safety Notice (GPIO 58 & GPIO 61 Traps)**:
> 1. **Switch Reset (GPIO 58)**: Driving GPIO 58 low asserts the hardware reset line of the RTL8367RB gigabit switch, instantly disconnecting all physical ethernet links across all 4 RJ45 jacks.
> 2. **SPI Flash Freezing (GPIO 61)**: Register `0xB8000820` bits `[3:0]` control pin multiplexing. Configuring GPIO 61 switches the SPI NOR flash interface pins to GPIO mode. This immediately cuts off CPU instruction fetching from the memory-mapped SPI Flash window (`0xBFC00000`), instantly freezing the Linux kernel and RootFS (SquashFS). This silicon reality fully explains 4PDA post #1948 ("exporting GPIO > 57 crashes the SoC").

### 6.2 UART Serial Console Pinout
A 4-pin unpopulated 2.54 mm header is located adjacent to the SoC heatsink on the PCB:
- **Pin 1 (Square Pad)**: **VCC (3.3V)** — *DO NOT CONNECT TO 5V UART ADAPTERS!*
- **Pin 2**: **GND** (Ground).
- **Pin 3**: **RXD** (SoC Receive, connects to USB-UART TXD).
- **Pin 4**: **TXD** (SoC Transmit, connects to USB-UART RXD).
- **Console Parameters**: **38400 baud**, 8 data bits, no parity, 1 stop bit (38400 8N1), no flow control.

### 6.3 Factory MAC Address Allocation Architecture in `mtd1`
The router's unique hardware MAC addresses are calculated from a single base MAC stored in SPI Flash partition `mtd1` (calibration/boot config sector, offsets `0x2086F`..`0x2087A` containing `HW_NIC0_ADDR=`):
- **Base MAC (`HW_NIC0_ADDR`)**: Assigned to **LAN Bridge / Switch CPU Port** (`eth0.2`).
- **Base MAC + 1 (`HW_WLAN1_WLAN_ADDR`)**: Assigned to **2.4 GHz Wireless Interface** (`wlan0`).
- **Base MAC + 2 (`WAN Interface`)**: Assigned to **WAN Ethernet Interface** (`eth0.1`) to ensure zero collision with wireless interfaces.
- **Base MAC + 5 (`HW_WLAN0_WLAN_ADDR`)**: Assigned to **5 GHz 802.11ac Wireless Interface** (`wlan1`).

Neither the bootloader nor the Linux kernel enforces a static CRC32 over `mtd1`. Consequently, calibration scripts such as `set-mib.sh` safely scan dynamically for `HW_NIC0_ADDR=` rather than relying on brittle static offsets.

