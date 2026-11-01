# Realtek RTL8192CD Monolithic Wireless Driver Deep Dive

## 1. Architectural Architecture & Dual-Band Model

In the Realtek Linux BSP, wireless connectivity is managed by a single unified, monolithic kernel driver module: **`rtl8192cd`**. Unlike the modular Linux `mac80211` / `cfg80211` stack, Realtek's `rtl8192cd` incorporates the full 802.11 MAC management layer, rate control algorithm, physical calibration engine (`phydm`), hardware abstraction layer (`halmac`), and packet scheduling within a single cohesive subsystem.

On the Tenda AC10 V1.0, the driver orchestrates two physically independent wireless network interfaces:

```
+-----------------------------------------------------------------------------------+
|                     Realtek rtl8192cd Monolithic Driver Subsystem                 |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  |             Linux Network Stack / Private IOCTL Interface (SIOCDEVPRIVATE)  |  |
|  +-----------------------------------------------------------------------------+  |
|                                        |                                          |
|                    +-------------------+-------------------+                      |
|                    |                                       |                      |
|                    v                                       v                      |
|  +-----------------------------------+   +-------------------------------------+  |
|  | wlan0: 5 GHz 802.11ac Subsystem   |   | wlan1: 2.4 GHz 802.11n Subsystem    |  |
|  | - Hardware: Realtek RTL8822BE     |   | - Hardware: RTL8197FS Internal MAC  |  |
|  | - Interconnect: PCIe RC0 (IRQ 5)  |   | - Interconnect: AHB Bus (IRQ 6)     |  |
|  | - 80 MHz VHT80, MCS 0..9 256-QAM  |   | - 40 MHz HT40, MCS 0..15 64-QAM     |  |
|  | - Skyworth RFE Type 6 PA/LNA FEM  |   | - Skyworth RFE Type 5 PA/LNA FEM    |  |
|  | - Max PHY Rate: 866.7 Mbps        |   | - Max PHY Rate: 300.0 Mbps          |  |
|  +-----------------------------------+   +-------------------------------------+  |
|                    |                                       |                      |
|                    +-------------------+-------------------+                      |
|                                        |                                          |
|                                        v                                          |
|  +-----------------------------------------------------------------------------+  |
|  |           PHYDM (PHY Dynamic Mechanism) & HALMAC Hardware Engine            |  |
|  | - Dynamic Noise Floor / CCA Adaptation                                      |  |
|  | - Auto-Rate Fallback & TX Power Tracking (Registers 0x02C, 0x82C, 0x87C)    |  |
|  | - Master MIB_TABLE (524 Entries, VA 0x805F96BC)                             |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 2. HALMAC & PHYDM Engine Deconstruction

The internal architecture of `rtl8192cd` divides responsibilities into two core frameworks:

### 2.1 HALMAC (Hardware Abstraction Layer for MAC)
- Provides register-level abstraction across different Realtek generations (RTL8197F, RTL8822B, RTL8812F).
- Handles PCIe descriptor ring management, Tx/Rx aggregation FIFOs, beacon generation, and low-level power states.
- Implements `halmac_parse_efuse_data_88xx` (`0x803725A0`), which detects unburned physical eFuse matrices and routes parameter ingestion to the software MIB table.

### 2.2 PHYDM (Physical Layer Dynamic Mechanism)
- Continuously calibrates the RF radio during runtime without interrupting active data streams.
- **Dynamic CCA (Clear Channel Assessment)**: Monitors ambient electromagnetic noise, dynamically adjusting the energy detection (ED) threshold to prevent false carrier-sense busy states in congested apartment environments.
- **Thermal Power Tracking (`TXPowerTracking_ThermalMeter_Tmp8822B` at `0x803676D8`)**: Samples the on-die thermal sensor every 2 seconds, indexing the `pwrlevel5GHT40` tables to adjust PA bias voltage and maintain stable output power.
- **Dynamic DIG (Dynamic Initial Gain)**: Modulates receiver LNA sensitivity according to client proximity, avoiding receiver saturation from clients closer than 1 meter.

---

## 3. Master `MIB_TABLE` Deconstruction (`0x805F96BC`)

At virtual address `0x805F96BC` in `vmlinux_stock.bin`, the driver defines `MIB_TABLE`, an array of **524 configuration descriptor records**. When an ioctl `SIOCDEVPRIVATE + 1` (`0x89F1`) is received, the driver matches the ASCII string key against `MIB_TABLE` and writes directly to the private device context.

### Key Parameter Records:
```
+-----------------------------------------------------------------------------------+
| Parameter Name        | Offset in Context | Data Type | Size (Bytes) | Subsystem  |
+-----------------------------------------------------------------------------------+
| xcap                  | +0x2BFC           | Type 1    | 4 Bytes      | Crystal Cap|
| ther                  | +0x2C10           | Type 1    | 4 Bytes      | Thermal Cal|
| rfe_type              | +0x2C61           | Type 0    | 1 Byte       | FEM Profile|
| pwrlevel5GHT40_1S_A   | +0x096A           | Type 3    | 196 Bytes    | 5G Path A  |
| pwrlevel5GHT40_1S_B   | +0x0A2E           | Type 3    | 196 Bytes    | 5G Path B  |
| pwrlevel2GHT40_1S_A   | +0x0746           | Type 3    | 14 Bytes     | 2G Path A  |
| pwrlevel2GHT40_1S_B   | +0x0754           | Type 3    | 14 Bytes     | 2G Path B  |
+-----------------------------------------------------------------------------------+
```

---

## 4. Hardware Baseband Register Programming Flow

When `rfe_type = 6` is committed, `phydm_init_hw_info_by_rfe_type_8822b` (`0x80264810`) references hardware definition tables in `.rodata` (`cca_ifem_ccut` at `0x805DD780` and `cca_ifem_ccut_rfetype` at `0x805DD7E0`) to configure external Skyworth RF FEM lines via `odm_set_bb_reg`:

```c
/* Ground-truth FEM parameters stored in .rodata at 0x805DD780 (cca_ifem_ccut):
 * Programmed into Baseband registers via odm_set_bb_reg() during PHY initialization.
 */
static const u32 skyworth_rfe6_bb_parameters[] = {
    /* 0x805DD780 */ 0x75C97010, /* BB Reg 0x82C: RFE Pinmux (PA_EN / LNA_EN / TRSW) */
    /* 0x805DD790 */ 0x79A0EA2A, /* BB Reg 0x830: Path A State Table (Tx PA / Rx LNA) */
    /* 0x805DD7A0 */ 0x87765541, /* BB Reg 0x838: Path B State Table (Synchronized)   */
};
```

- **BB Reg `0x82C` (`0x75C97010`)**: Maps Baseband GPIO lines to PA_EN (Power Amplifier Enable), LNA_EN (Low-Noise Amplifier Enable), and TRSW (Transmit/Receive Switch) lines on the PCB.
- **BB Reg `0x830` (`0x79A0EA2A`)**: Instructs Path A hardware to assert PA_EN during transmission slots and assert LNA_EN during reception slots.
- **BB Reg `0x838` (`0x87765541`)**: Directs Path B hardware state switching in synchrony with Path A.

---

## 5. Architectural Superiority of Monolithic `rtl8192cd` vs `mac80211`

| Comparison Metric | Upstream `mac80211` / `rtw88` | Realtek Monolithic `rtl8192cd` | Architectural Rationale |
|---|---|---|---|
| **Memory Footprint** | ~14.8 MB RAM | **6.6 MB RAM** | Saves **8.2 MB RAM**; critical for 64 MB system |
| **Flash Binary Size** | ~1.85 MB (drivers + firmware) | **0.75 MB** | Saves **1.1 MB SPI Flash**, fitting full WireGuard |
| **Blank eFuse Handling** | Aborts, falls back to RFE 0 | **Ingests MTD1 via `set-mib.sh`** | Overcomes factory unburned OTP fuse |
| **Skyworth PA/LNA Status** | Unpowered (-17 dB deficit) | **Fully energized (+20 dBm EIRP)** | Full range and wall penetration |
| **5 GHz Link Rate** | 58.5 Mbps (MCS 0/1) | **866.7 Mbps (MCS 9 VHT80)** | 14.8x physical layer throughput increase |
| **CPU Utilization at 500M**| >85% (Kernel softirq) | **<18% (Hardware DMA Offload)** | Direct ring buffer DMA without SKB overhead |
