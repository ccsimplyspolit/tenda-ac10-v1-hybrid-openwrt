# Offline TFTP Recovery & 1-Click Flashing Guide (EN)

> **Navigation:** [Home (EN)](EN-Home) | [Русская версия](RU-Offline-TFTP-Recovery-Guide) | [Wiki Portal](Home)

On Tenda AC10 V1.0, **Realtek Booter v3.4.11B.9** lives in the read-only first 128 KB of SPI NOR flash (`mtd0`, `0x000000..0x020000`). Even after a power cut mid-upgrade or a bad kernel image, you can unbrick or flash over a standard Ethernet cable in two minutes without opening the case.

---

## 1. Three Hardware Quirks You Need to Know First

1. **Blue WAN is physically powered down in bootloader mode (`0x8000ED48`).** `rtk_port_phy_power_down(3)` cuts link on the WAN port during recovery. Plug your cable strictly into yellow **LAN 1, LAN 2, or LAN 3**.
2. **`ping 192.168.1.6` will never answer (`0x80001010`).** The bootloader's IPv4 filter drops everything except `UDP` (`0x11`) — there is zero ICMP Ping code in ROM. It replies to ARP (`50:0F:F5:00:00:01`) and accepts TFTP writes on `UDP:69` immediately.
3. **Never flash 2-segment `cs6c` + `hsqs` images (`0x80001C2C`).** A branch delay-slot bug (`move $s7, $s2` with `$s2=0`) writes the second segment to `0x00000000`, erasing `mtd0`. Always use our single-segment `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin` or verified `Tenda_AC10_V1_Stock_TFTP_Recovery.bin`.

---

## 2. Recommended: 1-Click Offline Scripts for Windows

Grab `Tenda_AC10_V1_Offline_Autonomous_Toolkit.zip` from [Releases](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/releases/latest) (or open `offline_autonomous_tools/` in the repo):

1. Plug Ethernet into yellow **LAN 1, LAN 2, or LAN 3**.
2. Right-click -> **Run as Administrator**:
   - **`Flash_Hybrid_OpenWrt_4.14_TFTP.bat`** — flashes **Hybrid OpenWrt 4.14.187** (`factory.bin`);
   - **`Offline_TFTP_Recovery_and_Flash.bat`** — restores clean **Stock Tenda `V15.03.06.23`**.
3. Unplug 12V power, hold **`RST/WPS`**, plug power back in, keep holding **7–12 seconds** until `SYS` blinks, then release.
4. The script pre-validates headers/checksums, sets temporary static IP `192.168.1.116`, detects the bootloader via ARP, streams the image to `192.168.1.6:69` in ~7 seconds, waits for flash burn + watchdog reboot, and **unconditionally restores your PC NIC to DHCP** inside `finally`.
5. Open `http://192.168.0.1` (and run **`Configure_OpenWrt_ISP_WAN_and_WiFi.bat`** to migrate your cloned ISP WAN MAC and Wi-Fi settings from `RouterCfm.cfg` in 10 seconds).

---

## 3. Manual TFTP Commands (Windows CMD / Tftpd64 / Linux)

1. Plug into **LAN 1–3** and set static IPv4 `192.168.1.100`, mask `255.255.255.0`, gateway `192.168.1.6`.
2. Hold `RST/WPS` while plugging in power for **10 seconds**, then release.
3. Push `factory.bin` directly to `192.168.1.6` without waiting for ping:
   - **Windows CMD:** `tftp -i 192.168.1.6 PUT tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin`
   - **Linux / macOS:** `curl -T tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin tftp://192.168.1.6/firmware.bin`
   - **Tftpd64:** *Tftp Client* tab -> Host `192.168.1.6`, Port `69`, Local File `factory.bin` -> **Put**.
4. Wait ~90 seconds for flash write and automatic reboot, switch your PC NIC back to DHCP, and browse to `http://192.168.0.1`.
