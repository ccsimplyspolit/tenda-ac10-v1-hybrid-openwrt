# Tenda AC10 V1.0 — Hybrid OpenWrt 4.14 Firmware, Stock Flash Partitions, Reverse Engineering & Offline TFTP Recovery Suite (RU / EN)

[![Build Tenda AC10 V1.0 Hybrid OpenWrt 4.14](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/actions/workflows/build-ac10-hybrid-openwrt.yml/badge.svg)](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/actions/workflows/build-ac10-hybrid-openwrt.yml)

> **Языки / Languages:** Полная документация на **Русском** и **Английском** языках доступна ниже и в разделе **[Wiki](wiki/Home.md)** ([GitHub Wiki](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/wiki)).

---

## Содержание репозитория (RU) | Repository Structure (EN)

1. **[`01_Stock_Firmware_and_Partitions/`](01_Stock_Firmware_and_Partitions/)** — Оригинальная заводская прошивка Tenda `V15.03.06.23_multi` для восстановления по TFTP (`Tenda_AC10_V1_Stock_TFTP_Recovery.bin`), дампы разделов `mtd0` (загрузчик), `booter_stage2` (`v3.4.11B.9`), `mtd1` (40 ключей заводской RF-калибровки, очищенные от личных MAC), `mtd2` (`kernel_cr6c`), `mtd3` (`rootfs_squashfs_tenda_xz`), таблица из 31,434 символов ядра `kallsyms` и шаблон оптимизированного конфига `RouterCfm_optimized_template.cfg` (все личные пароли и MAC заменены на плейсхолдеры `<YOUR_...>`).
2. **[`02_Compiled_Hybrid_OpenWrt_4.14_Firmware/`](02_Compiled_Hybrid_OpenWrt_4.14_Firmware/)** — Готовые скомпилированные и проверенные образы **Гибридной OpenWrt 4.14 (Linux 4.14.187)** для Tenda AC10 V1.0:
   - `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin` (`5,546,630` Б, `cs6c` @ `0x00030000`, SHA-256: `14be13fa1dec37ba38296fff3d08839aaf5664889774cd99a8f4d02029015dfa`) — для 1-клик прошивки через загрузчик по TFTP (`Flash_Hybrid_OpenWrt_4.14_TFTP.bat`).
   - `tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin` (`5,546,630` Б, `cs6c` @ `0x00030000`) — для обновления из OpenWrt (`sysupgrade -v`).
   - `tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin` (`5,546,694` Б, 64-байтный заголовок `TRX2` `ver=0x00030028` + `cs6c`, SHA-256: `0cf86960d3fe860888ed49200b8dd86ed5114198f74887715535b473d42f39f9`) — для прямой прошивки через штатный веб-интерфейс Tenda (`/cgi-bin/upgrade`).
   - `tenda-ac10-v1.dtb` (`4,218` Б) — скомпилированное дерево устройств (`Device Tree Blob`).
3. **[`Tenda_AC10_V1_Hybrid_Kit/`](Tenda_AC10_V1_Hybrid_Kit/) & [`offline_autonomous_tools/`](offline_autonomous_tools/) & [`Tenda_AC10_V1_Autonomous_Recovery_Suite/`](Tenda_AC10_V1_Autonomous_Recovery_Suite/)** — Исходный код сборки Гибридной OpenWrt 4.14 (`tenda-ac10-v1.dts`, `set-mib.sh`, `kernel-4.14.config.diff`, `build_hybrid_openwrt_ac10.sh`), автономные 1-клик утилиты TFTP-прошивки и восстановления (`Flash_Hybrid_OpenWrt_4.14_TFTP.bat`, `Offline_TFTP_Recovery_and_Flash.bat`, `tftp_recovery_engine.py`, `Emergency_Restore_PC_Network_DHCP.bat`) и автотесты (`Verify_All_Dumps_Chips_and_Backups.py`, `Test_Offline_Autonomous_Tools_Loopback.py`).
4. **[`03_Reverse_Engineering_and_Forensic_Analysis/`](03_Reverse_Engineering_and_Forensic_Analysis/)** — Полные отчёты по реверс-инжинирингу загрузчика `Realtek Booter v3.4.11B.9`, стокового ядра `Linux 3.10.90`, аппаратного NAT `rtl819x_hwnat`, коммутатора `RTL8367RB-VB`, таблиц `mib_table` и виртуального EFUSE `halmac_parse_efuse_data_88xx` (`RTL8822BE`), нестандартного сжатия `Tenda SquashFS-XZ`, а также все Python-скрипты дизассемблирования и распаковки.
5. **[`wiki/`](wiki/Home.md)** — Подробная двуязычная Wiki (RU + EN) по архитектуре, прошивке, восстановлению и калибровке.

---

## Быстрый старт: Как прошить Гибридную OpenWrt 4.14 или вернуться на Сток (RU)

### Вариант 1: Прошивка в 1 клик по TFTP через загрузчик (Рекомендуемый и самый надёжный способ)
1. Подключите компьютер сетевым кабелем в порт **LAN 1, LAN 2 или LAN 3** роутера (**не в WAN!** В режиме загрузчика порт WAN = Порт 3 принудительно отключён).
2. Запустите от имени Администратора:
   - Для установки **Hybrid OpenWrt 4.14**: [`offline_autonomous_tools/Flash_Hybrid_OpenWrt_4.14_TFTP.bat`](offline_autonomous_tools/Flash_Hybrid_OpenWrt_4.14_TFTP.bat)
   - Для возврата на **заводской сток Tenda**: [`offline_autonomous_tools/Offline_TFTP_Recovery_and_Flash.bat`](offline_autonomous_tools/Offline_TFTP_Recovery_and_Flash.bat)
3. Зажмите кнопку **RST/WPS** на роутере, включите питание, удерживайте кнопку **5–7 секунд** и отпустите.
4. Скрипт автоматически обнаружит загрузчик по адресу `192.168.1.6`, передаст проверенный образ по `UDP:69`, дождётся записи во флеш-память и перезагрузки (`~45–60 секунд`), после чего автоматически вернёт сетевую карту вашего ПК в режим DHCP!

### Вариант 2: Обновление напрямую через штатный веб-интерфейс Tenda
1. Зайдите на `http://192.168.0.1` -> *Системные настройки* -> *Обновление прошивки*.
2. Выберите файл [`02_Compiled_Hybrid_OpenWrt_4.14_Firmware/tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`](02_Compiled_Hybrid_OpenWrt_4.14_Firmware/tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin).
3. После перезагрузки (~90 секунд) роутер будет доступен по адресу `http://192.168.1.1` (SSID: `Tenda-AC10-5G` и `Tenda-AC10-2G`).

---

## Quick Start: Flashing Hybrid OpenWrt 4.14 or Restoring Stock Firmware (EN)

### Option 1: 1-Click Bootloader TFTP Flash (Recommended & De-Bricks Any State)
1. Plug your PC Ethernet cable into **LAN 1, LAN 2, or LAN 3** (**never WAN!** Bootloader powers down WAN Port 3 PHY `0x1940`).
2. Right-click and **Run as Administrator**:
   - To flash **Hybrid OpenWrt 4.14**: [`offline_autonomous_tools/Flash_Hybrid_OpenWrt_4.14_TFTP.bat`](offline_autonomous_tools/Flash_Hybrid_OpenWrt_4.14_TFTP.bat)
   - To restore **Stock Tenda Firmware**: [`offline_autonomous_tools/Offline_TFTP_Recovery_and_Flash.bat`](offline_autonomous_tools/Offline_TFTP_Recovery_and_Flash.bat)
3. Hold the **RST/WPS** button, power on the router, keep holding for **5–7 seconds**, then release.
4. The script automatically detects the bootloader at `192.168.1.6`, streams the verified firmware image over `UDP:69`, waits for flash write + auto-reboot, and restores your PC's network adapter to DHCP.

### Option 2: Direct Upload via Stock Tenda Web UI
1. Open `http://192.168.0.1` -> *System Settings* -> *Firmware Upgrade*.
2. Upload [`02_Compiled_Hybrid_OpenWrt_4.14_Firmware/tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`](02_Compiled_Hybrid_OpenWrt_4.14_Firmware/tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin).
3. After reboot (~90 seconds), OpenWrt 4.14 will be live at `http://192.168.1.1` (SSIDs: `Tenda-AC10-5G` and `Tenda-AC10-2G`).
