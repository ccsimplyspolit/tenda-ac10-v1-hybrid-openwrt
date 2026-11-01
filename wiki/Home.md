# Tenda AC10 V1.0 — Bilingual Engineering Wiki & Documentation Portal (RU / EN)

> **Добро пожаловать! / Welcome!**  
> Данная база знаний содержит полную техническую документацию, результаты бинарного реверс-инжиниринга, руководство по аварийному TFTP-восстановлению и две стабильные прошивки для маршрутизатора **Tenda AC10 V1.0**.  
> This knowledge base provides comprehensive technical documentation, silicon-level reverse-engineering dossiers, offline disaster recovery procedures, and two production firmware solutions for the **Tenda AC10 V1.0** gigabit wireless router.

---

## Языковые разделы / Language Portals

| 🇷🇺 Русскоязычный раздел (RU) | 🇬🇧 English Documentation Section (EN) |
| :--- | :--- |
| **[Перейти к полному разделу на русском языке (ru/Home.md)](ru/Home.md)** | **[Go to Full English Documentation Section (en/Home.md)](en/Home.md)** |
| Прямая ссылка: `[[ru/Home]]` | Direct link: `[[en/Home]]` |

---

## Навигационная матрица / Documentation Matrix

| Тема / Topic | 🇷🇺 Документация (RU) | 🇬🇧 Documentation (EN) | Описание / Description |
| :--- | :--- | :--- | :--- |
| **Аппаратная архитектура** | **[Аппаратная архитектура](ru/Hardware-Architecture.md)** | **[Hardware Architecture](en/Hardware-Architecture.md)** | Архитектура RTL8197FS, 64 МБ SiP, 8 МБ Flash, RTL8822BE, RTL8367RB, GPIO |
| **Реверс-инжиниринг** | **[Бинарный реверс-инжиниринг](ru/Binary-Reverse-Engineering.md)** | **[Binary Reverse Engineering](en/Binary-Reverse-Engineering.md)** | Дизассемблирование Booter v3.4.11B.9, ядро `cr6c`, HWNAT ASIC TLU, Unicorn 2.1.4 |
| **Оптимизация Stock+** | **[Оптимизация Stock+](ru/Stock-Plus-Optimization.md)** | **[Stock+ Optimization](en/Stock-Plus-Optimization.md)** | Очистка стока от телеметрии `/bin/ucloud_v2`, патч uTP/торрентов, шаблон CFG |
| **Порт Hybrid OpenWrt 4.14** | **[Порт Hybrid OpenWrt 4.14](ru/Hybrid-OpenWrt-4.14-Port.md)** | **[Hybrid OpenWrt 4.14 Port](en/Hybrid-OpenWrt-4.14-Port.md)** | Ядро Linux 4.14 LTS, дерево DTS, инжектор калибровок `set-mib.sh`, LuCI |
| **TFTP-восстановление** | **[TFTP-восстановление](ru/Offline-TFTP-Recovery-Guide.md)** | **[Offline TFTP Recovery Guide](en/Offline-TFTP-Recovery-Guide.md)** | Раскирпичивание в 1 клик, метод удержания RST 15 секунд, автономный Python-сервер |
| **Частые вопросы (FAQ)** | **[Частые вопросы (FAQ)](ru/FAQ-and-Troubleshooting.md)** | **[FAQ & Troubleshooting](en/FAQ-and-Troubleshooting.md)** | Разбор ошибок Web UI, несовместимость с AC10 V3.0 (eCos), выбор канала 5 GHz |

---

## Аппаратные характеристики / Hardware Specifications

| Компонент / Component | Параметр / Specification | Описание и особенности / Engineering Notes |
| :--- | :--- | :--- |
| **SoC / Процессор** | Realtek RTL8197FS-VE5 | 1.0 GHz MIPS 24KEc (Lexra RLX5281, архитектура `mipsel`) |
| **RAM / Оперативная память** | 64 MB DDR2 SDRAM | System-in-Package (SiP), интегрирована прямо в корпус процессора |
| **SPI Flash / ПЗУ** | 8 MB SPI NOR Flash | Winbond W25Q64FV / W25Q64JV (`0xEF4017`, 8,388,608 байт) |
| **2.4 GHz Wi-Fi** | Realtek RTL8197FS SoC WMAC | 2T2R 802.11b/g/n (до 300 Мбит/с), Skyworth RFE Type 5 FEM |
| **5 GHz Wi-Fi** | Realtek RTL8822BE PCIe | 2T2R 802.11a/n/ac Wave 2 (до 866.7 Мбит/с), Skyworth RFE Type 6, чистый eFuse |
| **Switch / Коммутатор** | Realtek RTL8367RB-VB | 5-портовый Gigabit Switch, шина RGMII Port 6, SMI (GPIO 18/19), Reset (GPIO 58) |
| **Порты Ethernet** | 1x WAN, 3x LAN (1000Base-T) | **WAN = Порт коммутатора 3** (обесточен в Booter!), LAN1..LAN3 = Порты 2, 1, 0 |
| **Загрузчик / Bootloader** | Realtek Booter v3.4.11B.9 | Аварийный TFTP-сервер на `192.168.1.6:69`, ожидаемый IP ПК: `192.168.1.x` |

---

## Краткий обзор проекта (RU)

Репозиторий объединяет полный архив исследований кремния, побитового дизассемблирования и готовые инструменты для **Tenda AC10 V1.0**:

1. **Аппаратный NAT (`rtl819x_hwnat`)**: Скорость маршрутизации 940 Мбит/с при 0% нагрузки на процессор за счет аппаратного ускорения ASIC TLU.
2. **Двухдиапазонный Wi-Fi с заводской калибровкой**:
   - 5 ГГц (`RTL8822BE`): 866.7 Мбит/с (VHT80) благодаря динамическому инжектору калибровок `set-mib.sh` и `xtal_cap_override=27`.
   - 2.4 ГГц (`RTL8197FS`): 300 Мбит/с (HT40) с таблицами мощности из заводского раздела `mtd1`.
3. **Два направления прошивок**:
   - **Stock+**: Полная очистка заводской прошивки от телеметрии `/bin/ucloud_v2`, отключение шпионских сокетов, фикс отвалов Wi-Fi при торрентах (`manual_edca=1`).
   - **Hybrid OpenWrt 4.14**: Современный стек Linux 4.14 LTS с веб-интерфейсом LuCI, поддержкой WireGuard, пакетов `opkg` и аппаратным NAT.
4. **100% автономное TFTP-восстановление**: Комплекс скриптов на Python для раскирпичивания роутера по сети в 1 клик без пайки и UART-кабелей.

---

## Executive Overview (EN)

This knowledge base combines silicon-level hardware analysis, binary disassembly, and ready-to-deploy tools for the **Tenda AC10 V1.0**:

1. **Wire-Speed Hardware NAT Offload (`rtl819x_hwnat`)**: Sustained 940 Mbps line-rate throughput at 0% CPU overhead via Realtek ASIC Table Lookup Unit (TLU).
2. **Dual-Band Wi-Fi with Live Factory RF Calibration**:
   - 5 GHz (`RTL8822BE`): Full 866.7 Mbps (VHT80) operation powered by `set-mib.sh` virtual calibration synthesis and crystal cap override (`XCAP=27`).
   - 2.4 GHz (`RTL8197FS`): 300 Mbps (HT40) operation using factory power tables parsed from `/dev/mtd1`.
3. **Two Distinct Production Firmware Tracks**:
   - **Stock+**: Factory firmware de-bloated, telemetry daemon `/bin/ucloud_v2` eliminated, and uTP / BitTorrent Wi-Fi dropouts resolved via `manual_edca=1`.
   - **Hybrid OpenWrt 4.14**: Modern Linux 4.14 LTS platform featuring LuCI Web UI, WireGuard, `opkg` package repository, and hardware NAT offload.
4. **Autonomous Offline Disaster Recovery**: Python-based 1-click unbricking suite restoring corrupted devices over Ethernet without physical disassembly or serial cables.

---

## Быстрый старт / Quick Start

### Прошивка Hybrid OpenWrt 4.14 / Flashing OpenWrt 4.14
- **Способ 1 (TFTP в 1 клик / 1-Click TFTP)**:
  1. Подключите сетевой кабель ПК в порт **LAN 1, LAN 2 или LAN 3** (**не WAN!**).
  2. Запустите скрипт `offline_autonomous_tools/Flash_Hybrid_OpenWrt_4.14_TFTP.bat` от имени Администратора.
  3. Зажмите кнопку **RST/WPS**, включите питание роутера, удерживайте 5–7 секунд и отпустите.
  4. Скрипт передаст образ `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin` по TFTP, дождётся записи и вернёт сетевую карту ПК в режим DHCP.
- **Способ 2 (Через веб-интерфейс стока / Stock Web UI)**:
  1. Перейдите в веб-интерфейс `http://192.168.0.1` -> *Системные настройки* -> *Обновление прошивки*.
  2. Загрузите файл `02_Compiled_Hybrid_OpenWrt_4.14_Firmware/tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`.

### Возврат на заводскую прошивку / Restoring Stock Firmware
- Запустите `offline_autonomous_tools/Offline_TFTP_Recovery_and_Flash.bat` от имени Администратора и переведите роутер в режим загрузчика (удержание RST при включении).

---

## Полезные ссылки / Useful Links

- **GitHub Repository**: [tenda-ac10-v1-hybrid-openwrt](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt)
- **Releases & Binary Images**: [GitHub Releases](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/releases)
- **Сообщество 4PDA / Community Thread**: [4PDA Тема 885989: Tenda AC10 – Обсуждение](https://4pda.to/forum/index.php?showtopic=885989)
