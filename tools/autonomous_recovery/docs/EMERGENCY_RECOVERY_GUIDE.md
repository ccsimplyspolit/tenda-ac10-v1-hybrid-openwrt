# Tenda AC10 V1.0 - Autonomous Emergency Recovery & Unbricking Guide

This document is the authoritative, 100% offline manual for unbricking, recovering, and flashing the **Tenda AC10 V1.0** wireless router under Windows 11 without requiring internet access, external pip packages, or third-party flashing utilities.

---

## 1. Hardware Silicon & Flash Architecture

Forensic reverse engineering of the physical PCB, stock firmware `V15.03.06.52_multi`, and `Realtek Booter v3.4.11B.9` established the following exact parameters:

| Component | Specification | Operational Role & Notes |
|---|---|---|
| **SoC / CPU** | Realtek RTL8197FS | 1 GHz MIPS 24KEc (7-stage pipeline), 64 MB DDR2 SDRAM |
| **Switch** | Realtek RTL8367RB-VB | 5x Gigabit PHYs + RGMII MAC (SMI GPIO 18/19, Reset GPIO 58) |
| **SPI Flash** | Winbond W25Q64FVSIG | 8 MB (8,388,608 bytes) SPI NOR Flash |
| **Wi-Fi 2.4 GHz**| RTL8197FS internal | 2T2R 802.11b/g/n, Skyworth RFE Type 5 external PA/LNA |
| **Wi-Fi 5 GHz**  | Realtek RTL8822BE PCIe | 2T2R 802.11a/n/ac Wave 2 (up to 866.7 Mbps), Skyworth RFE Type 6 |
| **Bootloader**   | Realtek Booter v3.4.11B.9 | Embedded TFTP Server listening on **`192.168.1.6:69`** |
| **RAM Load Buffer**| `0x80A00000` (10 MB offset)| Statically mapped RAM buffer for incoming firmware |
| **Burn Destination**| `0x00030000` (192 KB) | Preserves Bootloader (0..128 KB) and RF Calibration `mtd1` (128..192 KB) |
| **Reset Button** | **GPIO 54** (Active-Low) | Polled at boot; triggers `"Entry disaster mode"` |

---

## 2. SPI Flash NOR Memory Map

```
0x000000 +---------------------------------------------------------+ 0 KB
         | mtd0: Bootloader Stage 1 & Stage 2 (Realtek Booter)     | 128 KB
0x020000 +---------------------------------------------------------+ 128 KB
         | mtd1: Factory Board Data & RF Calibration (40 TLV keys) | 64 KB
0x030000 +---------------------------------------------------------+ 192 KB
         | mtd2: Kernel Container (cr6c / cvimg header)            |
         | mtd3: RootFS (SquashFS 4.0 Tenda-XZ / OpenWrt RootFS)   | Max Partition Size:
         |       Combined Kernel + RootFS                          | 7,872 KB
         |                                                         | (8,060,928 Bytes)
0x7E0000 +---------------------------------------------------------+ 8064 KB
         | mtd4: Primary CFM NVRAM Configuration (seq=341)         | 64 KB
0x7F0000 +---------------------------------------------------------+ 8128 KB
         | mtd5: Backup CFM NVRAM Configuration (seq=340)          | 64 KB
0x800000 +---------------------------------------------------------+ 8192 KB (8 MB Total)
```

> **CRITICAL PARTITION WARNING:**
> The flash area between `0x030000` and `0x7E0000` has a strictly enforced maximum capacity of **8,060,928 bytes** (7,872 KB). Any firmware binary larger than 8,060,928 bytes will overwrite the CFM NVRAM partitions at `0x7E0000`, causing continuous reboot loops upon startup. `verify_firmware.py` automatically enforces this boundary.

---

## 3. Entering Bootloader Disaster Recovery Mode (GPIO 54)

The bootloader checks GPIO 54 during initial power-on. Holding the physical button forces the bootloader into permanent TFTP recovery server mode.

### Exact Timing Sequence:
1. **Cable Connection**: Connect a Gigabit Ethernet patch cable from your PC to router port **LAN1, LAN2, or LAN3** (yellow RJ-45 jacks).
   > **CRITICAL HARDWARE DIRECTIVE (WAN PHY POWER-OFF):**
   > **NEVER connect the cable to the blue WAN port!** Realtek `booter_stage2` at `0x8000ECE8` explicitly powers down the WAN PHY (`0x1940`). The WAN port is electrically dead in disaster recovery mode. Only LAN switch ports (LAN1–LAN3) are powered on and active.
2. **Power Off**: Disconnect the 12V DC power barrel connector from the router.
3. **Engage RST**: Using a paperclip or SIM-eject pin, **PRESS and HOLD** the physical `RST/WPS` button on the rear panel.
4. **Power On**: While continuing to firmly press the RST button, plug the 12V DC power barrel back in.
5. **Wait 12 to 15 Seconds**:
   - The blue **SYS LED** will illuminate solid blue for ~4 seconds.
   - It will blink once briefly.
   - Between **12 and 15 seconds**, the SYS LED will begin a **FAST, STEADY PULSATION** (~10 Hz).
6. **Release Button**: Immediately release the RST button.
7. The router is now halted in **Realtek Booter Disaster Recovery Mode** at IP **`192.168.1.6`**.

### Bootloader Network Protocol (UDP Only — No ICMP Ping):
> **CRITICAL PROTOCOL NOTICE (ICMP PING DISCARDED):**
> Reverse engineering of `booter_stage2` at `0x80001010` (`lbu $v1, 0x17($v0); li $v0, 0x11; bne $v1, $v0, 0x80001578`) proves that the bootloader's minimal IPv4 engine processes **strictly UDP protocol 0x11** (TFTP port 69). **All ICMP Echo Requests (pings) are silently discarded by hardware design!**
> Do not attempt to run `ping 192.168.1.6`, as it will always report request timed out. The autonomous suite probes the router directly via non-blocking UDP TFTP WRQ packets.

---

## 4. One-Click Automated Emergency Recovery (Recommended)

The suite provides two one-click Windows launchers that completely automate adapter configuration, image verification, TFTP transmission, and network restoration:

### 4.1 To Revert to Factory Stock Firmware:
1. Double-click **`restore_stock_cfe.bat`**.
2. Windows UAC will prompt for Administrator privileges (required to set static IP). Click **Yes**.
3. Follow the on-screen prompts. The tool will:
   - Validate `backups\Tenda_AC10_V1_Stock_TFTP_Recovery.bin` (clean 7,588,884 B image, cr6c + hsqs, dual 0x0000 checksums).
   - Snapshot your existing network configuration to `network_state_backup.json`.
   - Set PC static IP `192.168.1.8/24` (Gateway `192.168.1.6`).
   - Open Windows Firewall for UDP port 69.
   - Probe for `192.168.1.6` and push the firmware via pure Python TFTP client.
   - Monitor the flashing process.
   - Automatically restore your PC adapter to automatic DHCP and DNS.
   - Monitor router reboot into stock Tenda firmware at `http://192.168.0.1`.

### 4.2 To Flash Custom OpenWrt or Hybrid Firmware:
Run via command prompt:
```cmd
run_emergency_recovery.bat --image "path\to\your_custom_firmware.bin"
```
Or with automatic checksum repair if flashing an uncompensated custom build:
```cmd
run_emergency_recovery.bat --image "path\to\your_custom_firmware.bin" --fix-checksum
```

---

## 5. Emergency Standalone Network Restorer (`restore_network.bat`)

If a flashing session is prematurely terminated, the command window is closed, or the PC is restarted while the adapter is in static recovery mode (`192.168.1.8`), you will not have internet access because DHCP is disabled.

### Instant Fix:
- Simply double-click **`restore_network.bat`**.
- It auto-elevates and executes `restore_network.ps1`, which reads `network_state_backup.json` (or auto-discovers the physical Intel/Realtek Ethernet adapter) and instantly restores automatic DHCP and DNS.
- Your internet connectivity will be restored within 3 seconds.

---

## 6. Manual Verification & Tool CLI Reference

All tools operate 100% offline using standard Python 3.

### 6.1 Validating a Firmware Image (`verify_firmware.py`):
```cmd
python verify_firmware.py backups\kernel_cr6c.bin
```
Output:
```text
========================================================================
  FIRMWARE INTEGRITY REPORT: kernel_cr6c.bin
========================================================================
  File Path:          backups\kernel_cr6c.bin
  Total Size:         2,145,298 bytes (2095.0 KB)
  Max Flash Limit:    8,060,928 bytes (7,872 KB)
  Size Compliance:    [PASS] SAFE
------------------------------------------------------------------------
  Magic Signature:    'cr6c' (63723663) -> Linux kernel + rootfs
  RAM Load Address:   0x80A00000 (Expected: 0x80A00000)
  Flash Burn Offset:  0x00030000 (192 KB)
  Burn Safe Check:    [PASS] PROTECTED
  Header Payload Len: 2,145,282 bytes
  16-Bit BE Checksum: 0x0000 (Expected: 0x0000)
  Checksum Status:    [PASS] VALID
========================================================================
  >>> VERIFICATION PASSED: IMAGE IS SAFE FOR TFTP RECOVERY <<<
========================================================================
```

### 6.2 Standalone TFTP Engine CLI (`tftp_emergency_engine.py`):
- **Client Push (WRQ)**:
  ```cmd
  python tftp_emergency_engine.py --mode client --ip 192.168.1.6 --file backups\mtd3_kernelfs.bin
  ```
- **Server Listen (RRQ)**:
  ```cmd
  python tftp_emergency_engine.py --mode server --ip 0.0.0.0 --port 69 --file backups\mtd3_kernelfs.bin
  ```

---

## 7. Forensic UART Serial Console Recovery

If the Ethernet interface fails or deep low-level boot diagnostics are required:

### 7.1 UART Pinout Header
Locate the 4-pin row of pads on the top side of the PCB, near the SoC shield and Wi-Fi front-end:
```
  [ 1 ]   ( 2 )   ( 3 )   ( 4 )
 [Square]  Round   Round   Round
  3.3V      TX      RX      GND
```
- **Pin 1 (Square pad)**: 3.3V VCC — **LEAVE DISCONNECTED** (connecting external power will damage the SoC).
- **Pin 2 (Round pad)**: TX — Connect to USB-UART Adapter **RX**.
- **Pin 3 (Round pad)**: RX — Connect to USB-UART Adapter **TX**.
- **Pin 4 (Round pad)**: GND — Connect to USB-UART Adapter **GND**.

*Voltage Level:* **3.3V TTL**. Do NOT use 5V logic levels.

### 7.2 Terminal Settings
- **Baud Rate**: `115200`
- **Data Bits**: `8`
- **Parity**: `None`
- **Stop Bits**: `1`
- **Flow Control**: `None`

### 7.3 Bootloader Interactive Shell Commands
Power on the router and immediately press `<ESC>` repeatedly. The prompt `<RealTek>` will appear:
```text
---Realtek RTL8197F boot code at 2018.06.01 10:14:22 (1000MHz)
DRAM Type: DDR2
DRAM Size: 64MB
---Ethernet init Okay!
<RealTek>
```
To flash manually from the serial prompt:
```text
ipconfig 192.168.1.6
ping 192.168.1.8
tftp 0x80a00000 firmware.bin
flash write 0x80a00000 0x00030000 <length_in_hex>
reboot
```

---

## 8. Hard Brick Recovery (CH341A SPI Hardware Programmer)

In the event of a catastrophic corruption where the bootloader itself (`0x000000..0x020000`) is erased or damaged and the router displays no LED activity:

1. Attach an 8-pin SOIC8 test clip directly to the **Winbond W25Q64FVSIG** flash chip on the PCB.
2. Connect the test clip ribbon to a **CH341A USB SPI Programmer** (ensure programmer is set to 3.3V mode via jumper).
3. Connect CH341A to PC.
4. Using `flashrom` (Linux) or `AsProgrammer` / `NeoProgrammer` (Windows), flash the master full flash binary:
   ```bash
   flashrom -p ch341a_spi -c W25Q64.V -w backups/mtd0_fullflash.bin
   ```
5. Cryptographic verification:
   - Size: `8,388,608` bytes
   - SHA-256: `af40888b2a92539ef51218a7ed6dc25c48ac2cd51950ffcf25bec44b98252833`
6. Disconnect programmer and power on router. It will boot into factory condition with all calibration parameters intact.

---

## 9. Master Backups Manifest

Located in `backups\`:

| Filename | Size (Bytes) | SHA-256 Checksum | Purpose |
|---|---:|---|---|
| `mtd1_bootloader.bin` | 131,072 | `5f351f3bbcfa3a1b2a5f17bdcdd5191deec5685126bb0a5830f96788d8962036` | Realtek Booter v3.4.11B.9 |
| `mtd2_calibration.bin` | 65,536 | `2b0224aff5c250bf10c25d94c38a638496543cc2af1287a692c58855e269aba7` | Factory RF Calibration (40 TLV keys) |
| `kernel_cr6c.bin` | 2,145,298 | `023bc89c65c7c0c00ee6ca34b65c07644c3df62f3c38e76e760bcef54248dd33` | Stock Kernel Container (0x030000) |
| `mtd3_kernelfs.bin` | 8,060,928 | `4679fa4673696318288896d6518515db7c0db4e5defb88d8bfe552bc98181c45` | Combined Stock Kernel + RootFS |
| `RouterCfm_optimized.cfg`| 25,373 | `c9a3fa77df8c94a5f569eda802690805db12c214f5070b898d536552c4584d3e` | Optimized NVRAM Settings (br2/cloud off) |
| `SHA256SUMS.txt` | 465 | — | Cryptographic integrity manifest |
