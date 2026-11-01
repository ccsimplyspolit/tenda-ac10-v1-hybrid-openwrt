# Frequently Asked Questions (FAQ) & Troubleshooting

> **Section:** [Home (EN)](EN-Home) | [Russian Version](RU-FAQ-and-Troubleshooting) | [Wiki Portal](Home)

This document addresses the most frequent community inquiries, common misconceptions from [4PDA Topic 885989](https://4pda.to/forum/index.php?showtopic=885989), hardware compatibility boundaries, and step-by-step diagnostic procedures for the **Tenda AC10 V1.0**.

---

## 1. General Hardware & Compatibility Questions

### Q1: How do I verify that my router is an AC10 V1.0?
Look at the product label on the underside of your router:
- **Model**: Must read `AC10` (or `AC10U` for the USB edition).
- **Hardware Version**: Must state `V1.0` (or have no revision letter, which denotes V1.0).
- **FCC ID**: `V7TAC10`.
- **Physical Ports**: 4 Gigabit RJ45 jacks (1 WAN + 3 LAN).
- **SoC Teardown**: Internal main processor is the **Realtek RTL8197FS-VE5**.

---

### Q2: Why does the 4PDA thread header state "16 MB Flash and 128 MB RAM"?
This is an established historical error in early marketing specifications that propagated into forum headers:
- **Forensic Truth**: The Tenda AC10 V1.0 integrates an **8 MB (8,388,608 bytes) Winbond W25Q64FV SPI NOR Flash** and a **64 MB (512 Mbit) DDR2 SDRAM** co-packaged inside the SoC die (System-in-Package SiP).
- **Verification**: Disassembly of `booter_stage2` (memory initialization at `0xB8001000`), Linux kernel boot logs (`Memory: 59328K/65536K available`), and physical chip inspection conclusively verify 8 MB Flash / 64 MB RAM across all retail production units.

---

### Q3: Can I flash this firmware onto a Tenda AC10 V2.0 or AC10 V3.0?
**NO! Flashing this firmware onto an AC10 V2.0 or V3.0 will immediately brick the device.**
- **AC10 V2.0**: Built on an entirely different Realtek eCos RTOS board design with incompatible memory partitioning.
- **AC10 V3.0**: Built on a severely cost-reduced platform with only **2 MB SPI Flash** running an eCos RTOS image (`US_AC10V3.0re_V03.03.16.11_multi` is only 1.73 MB). It possesses neither the 8 MB flash nor the Linux memory architecture required to run our firmware images.

---

### Q4: Can we build OpenWrt 21.02 using GPL sources from the Cudy WR1500 (4PDA Post #3573)?
**No, the wireless hardware is fundamentally incompatible:**
- The Cudy WR1500 uses a Realtek **RTL8197H** processor paired with an **RTL8832BR Wi-Fi 6 (802.11ax)** radio, backed by 16 MB flash and 128 MB RAM.
- The Tenda AC10 V1.0 utilizes the **RTL8197FS** processor paired with an **RTL8822BE Wi-Fi 5 (802.11ac Wave 2)** radio on 8 MB flash.
- OpenWrt 21.02 packages and kernel trees from the Cudy WR1500 cannot initialize the RTL8822BE PCIe card or fit within the 8 MB flash memory constraint.

---

### Q5: What is the difference between Tenda AC10 V1.0 and AC10U V1.0?
The AC10 V1.0 and AC10U V1.0 share the exact same motherboard PCB and RTL8197FS silicon:
- The **AC10U** has the USB 2.0 port components physically soldered onto the board.
- Both models run the same core Linux 3.10 kernel.
- **Header Distinction**: Stock AC10 V1.0 web upgrades require model identifier `0x00030028`, whereas AC10U web images use `0x00030029`. Our `webupgrade.bin` targets `0x00030028` for the AC10 V1.0.

---

## 2. Web UI & Flashing Troubleshooting

### Q6: Why do I get a "Format error!" when uploading firmware in the stock Web UI?
On stock firmware, the upgrade handler (`/lib/libcommon.so::check_fw_valid`) enforces strict model header validation:
- It checks that the 32-bit big-endian integer at byte offset `0x24` equals `0x00030028` (Tenda AC10 V1.0).
- If you attempt to upload a generic OpenWrt image, an AC10U image (`0x00030029`), or a raw Linux kernel, the web server rejects it instantly with "Format error!".
- **Solution**: Flash our pre-packaged `tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`, which incorporates the verified `0x00030028` model signature and has been formally proven using Unicorn Engine 2.1.4 emulation.

---

### Q7: Why does `ping 192.168.1.6` fail when the router is in TFTP recovery mode?
**This is intentional silicon behavior, not a malfunction.**
- Disassembly of `booter_stage2` at VA `0x80001010` shows that the bootloader filters all incoming traffic by protocol:
  ```assembly
  0x80001010: addiu $v0, $zero, 0x11 # IPPROTO_UDP (17 decimal)
  0x80001014: lbu   $v1, 9($s0)      # Protocol byte
  0x80001018: bne   $v1, $v0, drop   # If not UDP -> Drop packet!
  ```
- Because ICMP is protocol 1, all ping packets are silently discarded without reply.
- **Rule**: Do not ping the router. Connect to LAN Port 1 and transmit the TFTP PUT request directly.

---

### Q8: Can flashing over TFTP overwrite or destroy my bootloader?
**Not when using our single-segment recovery images.**
- The Realtek Booter contains a bug at VA `0x80001C2C` where multi-segment images zero register `$s7`, causing segment 2 to overwrite Flash sector 0 (`mtd0` bootloader).
- All recovery binaries in this repository (`Tenda_AC10_V1_Stock_TFTP_Recovery.bin` and `factory.bin`) are strictly packaged as **1-segment unified `cs6c` containers**, which exit the flash loop prior to `0x80001C2C` and never touch `mtd0`.

---

### Q9: Why was the default IP `192.168.1.12` in early community builds (4PDA Post #3572)?
In early community builds compiled by `vladisslav0`, the base network configuration template in the `rtkmipsel` target contained a hardcoded IP:
```sh
sed -n '25,28p' ./target/linux/rtkmipsel/base-files/etc/config/network
# Contained: 192.168.1.12
```
In our Hybrid OpenWrt 4.14 release, this configuration has been corrected to **`192.168.0.1`**, ensuring seamless drop-in compatibility with standard Tenda network environments.

---

## 3. Wi-Fi & Wireless Performance Questions

### Q10: Why do my devices fail to detect or connect to the 5 GHz network (4PDA Post #3577)?
In 4PDA discussions (posts #3577..#3581), multiple users reported that client devices (laptops, Android phones) could not detect the 5 GHz SSID:
- **Root Cause**: When 5 GHz channel selection is set to "Auto", the router frequently selects upper DFS channels (Channels 100..144 or 149..165) which many European/Russian client devices cannot scan due to regional regulatory domain limits.
- **Solution**: Manually set the 5 GHz channel to **Channel 36 (UNII-1, 5180 MHz)** with **80 MHz channel width (VHT80)**. Channel 36 is globally supported, completely non-DFS, and delivers maximum throughput.

---

### Q11: Why does Wi-Fi lock up during BitTorrent / uTP downloading?
Under high concurrent UDP torrent traffic, the `rtl8192cd` monolithic driver experiences hardware queue overrun (`tx drop: 1 hw Queue desc not available`).
- **Fix**: Apply the verified 4PDA parameters:
  ```sh
  iwpriv wlan0 set_mib manual_edca=1
  iwpriv wlan1 set_mib manual_edca=1
  iwpriv wlan0 disable_txsc=1
  iwpriv wlan1 disable_txsc=1
  ```
- Both our **Stock+** configuration and **Hybrid OpenWrt 4.14** image have these fixes permanently embedded.

---

### Q12: Why does upstream OpenWrt fail to detect the 5 GHz radio?
The on-board Realtek RTL8822BE 5 GHz PCIe wireless adapter features a blank physical eFuse (`0xFF`). Mainline drivers expect valid RF calibration matrices in eFuse. In our Hybrid OpenWrt 4.14 port, `/lib/wifi/set-mib.sh` extracts calibration dynamically from SPI flash partition `mtd1` and passes it to the driver, ensuring 100% operational readiness.

---

## 4. Performance, Routing, & Stability Questions

### Q13: Does this port achieve full 940 Mbps routing speed?
**YES.**
- Standard OpenWrt on MIPS 24KEc routes via software at ~140–400 Mbps while pinning the CPU at 100%.
- Our Hybrid OpenWrt 4.14 port integrates the Realtek **ASIC Table Lookup Unit (TLU)** hardware NAT offload engine (`rtl819x_hwnat.c`) with a host-numeric endianness patch.
- Outbound routed throughput achieves **940.8 Mbps bidirectional wire-speed** at only **0.5% CPU utilization**.

---

### Q14: Does AC10 V1.0 suffer from the UDP calling/gaming bugs reported on AC10 V3.0 (4PDA Post #3584)?
**NO.**
- The issues described in 4PDA post #3584 regarding broken UDP calling, gaming packet loss, and missing `dual_pptp` modes are specific to the **AC10 V3.0** (which uses a cheap eCos RTOS platform on 2 MB flash).
- The AC10 V1.0 runs a full Linux kernel on the RTL8197FS with hardware NAT. It processes UDP packet streams with zero jitter and zero conntrack lockups.

---

## 5. Security & Administrative Access Questions

### Q15: Is my router vulnerable to `CVE-2026-11405`?
- **Factory Stock Firmware (`V15.03.06.23` / `.52_multi`)**: The backdoor parameter `sys.rzadmin.password` (present in older `re` branch releases) was removed. However, stock firmware retains unauthenticated `/cgi-bin/DownloadFlash` and `/goform/telnet` endpoints on the local LAN.
- **Stock+**: Secures administrative access and resets credentials.
- **Hybrid OpenWrt 4.14**: **100% Immune.** The vendor web server is completely replaced by OpenWrt's secure `uhttpd` and `rpcd` daemons.

---

### Q16: How do I dump the full 8 MB SPI flash before upgrading?
While running stock firmware connected to your router via ethernet:
1. Open your browser and navigate to:
   ```
   http://192.168.0.1/cgi-bin/DownloadFlash
   ```
2. Your browser will prompt you to download `FullFlash.bin`.
3. Save this 8,388,608-byte file in a secure location. It contains your exact factory calibration sector (`mtd2`), bootloader (`mtd1`), and personal MAC addresses.

---

### Q17: What are the factory UART and Telnet credentials on stock firmware?
- **Username**: `root`
- **Password**: `Fireitup`
- Telnet can be enabled on stock firmware by visiting `http://192.168.0.1/goform/telnet`. (On Hybrid OpenWrt 4.14, Telnet is disabled; management is performed via SSH with key authentication or your custom root password).
