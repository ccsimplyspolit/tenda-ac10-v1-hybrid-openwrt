# Tenda AC10 V1.0 — Hybrid OpenWrt 4.14, Stock Partitions, Reverse Engineering & Recovery Suite (RU / EN Wiki)

## Навигация по Wiki (Русский) | Wiki Navigation (English)

1. **[01 — Аппаратная платформа, чипы и разметка 8 МБ SPI NOR Flash / Hardware BOM, Silicon & 8 MB Flash Layout](01-Hardware-Silicon-and-Flash-Layout.md)**
2. **[02 — Реверс-инжиниринг загрузчика Realtek Booter v3.4.11B.9 и TFTP-прошивка / Bootloader RE & TFTP Recovery Guide](02-Bootloader-Stage2-and-TFTP-Recovery.md)**
3. **[03 — Архитектура гибридной прошивки OpenWrt 4.14 (HWNAT 940 Мбит/с + Wi-Fi 867 Мбит/с) / Hybrid OpenWrt 4.14 Architecture & Binary Patches](03-Hybrid-OpenWrt-4.14-Architecture-and-Patches.md)**
4. **[04 — Заводская RF-калибровка (mtd1, 40 ключей, EFUSE) и оптимизация NVRAM / RF Calibration, EFUSE Map & CFM NVRAM Forensics](04-RF-Calibration-and-NVRAM-Forensics.md)**

---

## Краткий обзор проекта (RU)

Этот репозиторий содержит полный цикл реверс-инжиниринга, дампы разделов флеш-памяти (с очищенными персональными данными), автономный комплекс аварийного восстановления по TFTP и собранную **гибридную прошивку OpenWrt 4.14 (Linux 4.14.187)** для маршрутизатора **Tenda AC10 V1.0** (`RTL8197FS-VE5` + `RTL8822BE` + `RTL8367RB-VB` + `Winbond W25Q64FV` 8 МБ):

- **Аппаратный NAT (`rtl819x_hwnat`) ~895–940 Мбит/с** при нулевой загрузке CPU (`0% SIRQ`) за счёт аппаратной маршрутизации L2/L3/L4 ASIC (`PORT0_ROUTER_MODE` + порядок байт хоста MIPS32 LE).
- **8 бинарных патчей ядра MIPS32 LE (`vmlinux` Linux 4.14.187)** для точного соответствия физической разводке портов коммутатора `RTL8367RB-VB` в Tenda AC10 V1.0 (**Физический порт WAN = Порт коммутатора 3**, битовая маска `0x08`, нечётный сдвиг регистра PVID `[31:16]`; **Физические порты LAN1..LAN3 = Порты коммутатора 2, 1, 0**, битовая маска `0x07`).
- **Двухдиапазонный Wi-Fi с заводской калибровкой из `/dev/mtd1`**:
  - **5 ГГц (`RTL8822BE` PCIe, `wlan1` / `phy0`)**: `rtw88_8822be.ko` + `rtw88_core xtal_cap_override=27` (`HW_WLAN0_11N_XCAP=27`) + инжектор виртуального EFUSE и регистров `set-mib.sh` (Skyworth `SE5003L1` RFE Type 6, VHT80 866.7 Мбит/с).
  - **2.4 ГГц (`RTL8197FS` SoC WMAC, `wlan0` / `phy1`)**: `rtl8192cd.ko` с автоматической подстановкой таблиц мощности и термокалибровки из `/dev/mtd1` (`RFE Type 5`, Skyworth `SKY85303-11`, `XCAP=46`, `THER=32`, HT40 300 Мбит/с).
- **Три готовых образа прошивки** (в папке [`02_Compiled_Hybrid_OpenWrt_4.14_Firmware/`](../02_Compiled_Hybrid_OpenWrt_4.14_Firmware/) и в GitHub Releases):
  1. `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin` — образ `cs6c` (`start_addr=0x80A00000`, `burn_addr=0x00030000`) для 1-клик прошивки через загрузчик по TFTP (`Flash_Hybrid_OpenWrt_4.14_TFTP.bat`).
  2. `tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin` — образ `cs6c` для обновления из запущенной OpenWrt (`sysupgrade -v`).
  3. `tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin` — образ с 64-байтным заголовком Tenda `TRX2` (`fw_type=2`, `model_version=0x00030028`, `zlib.crc32`) для прошивки напрямую через штатный веб-интерфейс Tenda (`/cgi-bin/upgrade`).

---

## Executive Overview (EN)

This repository provides the complete hardware/software reverse-engineering archive, sanitized SPI NOR flash partition dumps, 100% offline TFTP recovery suite, and compiled **Hybrid OpenWrt 4.14 (Linux 4.14.187)** firmware images for the **Tenda AC10 V1.0** (`RTL8197FS-VE5` + `RTL8822BE` + `RTL8367RB-VB` + `Winbond W25Q64FV` 8 MB):

- **~895–940 Mbps Hardware NAT (`rtl819x_hwnat`)** at `0% CPU SIRQ` via Realtek L2/L3/L4 ASIC table offload (`PORT0_ROUTER_MODE` + MIPS32 LE host-byte-order ASIC register stores).
- **8 Verified MIPS32 LE Kernel Binary Patches (`vmlinux` Linux 4.14.187)** adapting the RTL8197F switch/ASIC driver to Tenda AC10 V1.0's physical port routing (**Physical WAN = Switch Port 3**, mask `0x08`, odd-port PVID upper-halfword shift `[31:16]`; **Physical LAN1..LAN3 = Switch Ports 2, 1, 0**, mask `0x07`).
- **Dual-Band Wi-Fi with Live `/dev/mtd1` Factory RF Calibration**:
  - **5 GHz (`RTL8822BE` PCIe, `wlan1` / `phy0`)**: `rtw88_8822be.ko` + `rtw88_core xtal_cap_override=27` + `set-mib.sh` calibration injector (Skyworth `SE5003L1` RFE Type 6, VHT80 866.7 Mbps).
  - **2.4 GHz (`RTL8197FS` SoC WMAC, `wlan0` / `phy1`)**: `rtl8192cd.ko` with automatic `/dev/mtd1` calibration injection (`RFE Type 5`, Skyworth `SKY85303-11`, `XCAP=46`, `THER=32`, HT40 300 Mbps).
- **Three Ready-to-Flash Firmware Images** (in [`02_Compiled_Hybrid_OpenWrt_4.14_Firmware/`](../02_Compiled_Hybrid_OpenWrt_4.14_Firmware/) and GitHub Releases):
  1. `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin` — `cs6c` image (`start_addr=0x80A00000`, `burn_addr=0x00030000`) for 1-click bootloader TFTP flashing (`Flash_Hybrid_OpenWrt_4.14_TFTP.bat`).
  2. `tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin` — `cs6c` image for `sysupgrade -v` inside OpenWrt.
  3. `tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin` — `TRX2`-wrapped image (`fw_type=2`, `model_version=0x00030028`, `zlib.crc32`) for direct upload via stock Tenda Web UI (`/cgi-bin/upgrade`).
