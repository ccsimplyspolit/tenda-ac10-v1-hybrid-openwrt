# Tenda AC10 V1.0 Wiki & Practical Guide (EN)

> **Navigation:** [Wiki Portal](Home) | [Русский раздел (RU)](RU-Home) | [GitHub Pages](https://ccsimplyspolit.github.io/tenda-ac10-v1-hybrid-openwrt/)

Practical hardware notes, **Hybrid OpenWrt 4.14.187** firmware (`LuCI` at `192.168.0.1`), **Stock+** cleanup profile, 1-click offline Windows scripts, and TFTP unbricking instructions for the **Tenda AC10 V1.0** (`FCC ID: V7TAC10`).

> ⚠️ **Check the bottom label before flashing!**  
> Everything here applies **only to Tenda AC10 `Ver: V1.0`** (stock firmware `V15.03.06.xx`, 8 MB SPI NOR + 64 MB DDR2). Hardware revisions **V2.0 and V3.0** (`V02.03.xx` / `V03.03.xx`) use `RTL8197FH` with eCos RTOS and a **2 MB** flash chip — flashing any Linux image onto V2/V3 overwrites the bootloader and requires desoldering the flash chip.

---

## Live LuCI Interface (`v4.14.187-r2-ac10-hybrid`)

![LuCI Overview](https://raw.githubusercontent.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/main/docs/images/01_luci_status_overview.png)

---

## Wiki Sections

1. **[Hardware Architecture](EN-Hardware-Architecture)** — real board specs verified from flash dumps: `RTL8197FS-VE5` (1.0 GHz MIPS 24KEc with 64 MB DDR2 inside the package), 8 MB Winbond `W25Q64FV` SPI NOR (`0xEF4017` — dispelling the old 16 MB / 128 MB forum myth), `RTL8822BE` 5 GHz PCIe radio with blank `0xFF` OTP eFuse + Skyworth `SE5003L1` (`RFE 6`), `RTL8367RB` GbE switch (reset `GPIO 58`, odd WAN `Port 3`), and why touching `GPIO 59–62` instantly freezes the SoC.
2. **[Binary Reverse Engineering](EN-Binary-Reverse-Engineering)** — disassembly of `Realtek Booter v3.4.11B.9`: why `ping 192.168.1.6` never replies (`0x80001010` drops all non-UDP frames), why blue WAN is powered down in recovery (`0x8000ED48`), how the `$s7=0` delay-slot bug (`0x80001C2C`) erases `mtd0` on 2-segment `cs6c+hsqs` images, and how `libcommon.so` validates `0x00030028`.
3. **[Hybrid OpenWrt 4.14.187 Port](EN-Hybrid-OpenWrt-4.14-Port)** — how the `r2` build works in practice: all 14 live fixes baked in (ELF-patched `rtw88_8822b.ko` for `RFE Type 6` + `mtd1` `XCAP` injection + rock-solid `VHT20` ch36 `23 dBm`, concurrent wired + Wi-Fi via `Software Flow Offloading` with `hwnat=0`, cold-boot cloned WAN MAC polling, Apple RFC 9462 DDR HTTP/3 DoH without DNS warnings, WAN socket lockdown), live LuCI screenshots, and the 1-click ISP/Wi-Fi migrator.
4. **[Stock+ Optimization Guide](EN-Stock-Plus-Optimization)** — keep the stock Tenda UI while killing `/bin/ucloud_v2` cloud telemetry, removing phantom bridge `br2`, freeing ~6.8 MB RAM, and fixing BitTorrent/uTP stalls.
5. **[Offline TFTP Recovery & Scripts](EN-Offline-TFTP-Recovery-Guide)** — 1-click flashing and unbricking via `offline_autonomous_tools/Flash_Hybrid_OpenWrt_4.14_TFTP.bat` and `Offline_TFTP_Recovery_and_Flash.bat` with automatic PC DHCP rollback.
6. **[FAQ & Troubleshooting](EN-FAQ-and-Troubleshooting)** — straight answers to recurring community questions (`Format error!`, why Cudy WR1500 / DIR-842 images fail, and why colons corrupt `HW_NIC0_ADDR=` in `mtd1`).

---

## Quick Links

- Firmware & Scripts Download: [GitHub Releases (`Latest`)](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/releases/latest)
- Repository: [ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt)
- 4PDA Guide (#3585): [Topic 885989 Post #3585](https://4pda.to/forum/index.php?showtopic=885989&view=findpost&p=145799909)
