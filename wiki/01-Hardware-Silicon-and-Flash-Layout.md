# 01 — Аппаратная платформа, чипы и разметка 8 МБ SPI NOR Flash / Hardware BOM, Silicon & 8 MB Flash Layout

## 1. Спецификация микросхем (RU) | Hardware Silicon BOM (EN)

| Узел / Subsystem | Чип / Part Number | Подключение / Bus | Характеристики (RU) / Technical Details (EN) |
|---|---|---|---|
| **SoC + CPU + 2.4 ГГц** | **Realtek RTL8197FS-VE5** | MIPS32 24KEc (1000 МГц), On-chip 64 МБ DDR2 | Интегрированный 2.4 ГГц 802.11n 2T2R (`0x18640000`), аппаратный L2/L3/L4 NAT движок (`0x18010000`), контроллер PCIe RC (`0x18B00000`). |
| **FEM 2.4 ГГц** | **Skyworth SKY85303-11** × 2 | Внешний LNA + PA (`RFE Type 5`) | Заводская калибровка в `mtd1`: `HW_WLAN1_11N_XCAP=46`, `THER=32`, `RF_TYPE=5`. |
| **5 ГГц 802.11ac** | **Realtek RTL8822BE** | PCIe 1.1 x1 (`10ec:b822`) | 802.11ac MU-MIMO 2T2R (VHT80 866.7 Мбит/с), аппаратный декодер 512-байтного виртуального EFUSE (`halmac_parse_efuse_data_88xx`). |
| **FEM 5 ГГц** | **Skyworth SE5003L1** × 2 | Внешний LNA + PA (`RFE Type 6`) | Заводская калибровка в `mtd1`: `HW_WLAN0_11N_XCAP=27`, `THER=32`, `RF_TYPE=6`, `REG_DOMAIN=1`. |
| **Гигабитный свитч** | **Realtek RTL8367RB-VB** | RGMII (`extif1`, CPU Port 6) + SMI GPIO | Чип ID `0x6367` (`ver=0x0020`). Управление по шине SMI через **GPIO 18 (MDC/SCK)**, **GPIO 19 (MDIO/SDA)**, **GPIO 58 (аппаратный сброс)**. |
| **SPI NOR Flash** | **Winbond W25Q64FV** | SPI (`0x18143000` / MMIO `0xB0000000`) | 8 МБ (`8,388,608` байт), JEDEC ID `0xEF4017`, размер сектора стирания `4 КБ` (`0x1000`). |

---

## 2. Физическая распиновка портов коммутатора RTL8367RB-VB (RU / EN)

В отличие от референсных плат D-Link DIR-842 C2 / Greatek GWR1200AC (где WAN подключён к порту 4), в **Tenda AC10 V1.0** физические разъёмы RJ45 разведены следующим образом:

| Разъём на корпусе / Physical Jack | Порт RTL8367RB-VB / Switch Port | Битовая маска / Mask | VLAN в гибридной OpenWrt 4.14 / VLAN ID |
|---|---|---|---|
| **WAN (Жёлтый / Yellow)** | **Port 3** | `0x08` (`1 << 3`) | **VLAN 1 (`eth1`)** — порты `'3 6t'` (ASIC member `0x108`) |
| **LAN 1** | **Port 2** | `0x04` (`1 << 2`) | **VLAN 2 (`eth0` / `br-lan`)** — порты `'0 1 2 6t'` (ASIC member `0x107`) |
| **LAN 2** | **Port 1** | `0x02` (`1 << 1`) | **VLAN 2 (`eth0` / `br-lan`)** |
| **LAN 3 / IPTV** | **Port 0** | `0x01` (`1 << 0`) | **VLAN 2 (`eth0` / `br-lan`)** |
| **Линия CPU RGMII** | **Port 6 (`EXT_PORT0`)** | Тегированный `6t` | Соединён с внутренним портом ASIC `CPU Port 8` (`0x100`) |

---

## 3. Точная карта разделов 8 МБ SPI NOR Flash (RU / EN)

| Раздел / MTD | Смещение / Offset | Размер / Size | Сигнатура и контрольная сумма / Magic & Checksum | Назначение (RU) / Contents (EN) |
|---|---|---|---|---|
| `mtd0` (`boot`) | `0x000000..0x020000` | `128 КБ` (`131,072` Б) | MIPS BE bootvec `0x08001F43` + GZIP @ `0x007D60` | Загрузчик Stage-1 DDR2 init + сжатый Stage-2 **Realtek Booter v3.4.11B.9** (`102,496` Б в RAM по адресу `0x80000000`). |
| `mtd1` (`setting`) | `0x020000..0x030000` | `64 КБ` (`65,536` Б) | `[0x00:0x04]` LE CRC32 (`0xDEED2A7D`), `[0x04:0x08]` `0x00000000` | **КРИТИЧЕСКИЙ РАЗДЕЛ (НЕ СТИРАТЬ!)**: 40 ключей ASCII (`KEY=VALUE\0`) с заводской RF-калибровкой 2.4G/5G и базовыми MAC-адресами. |
| `mtd2` (`kernel` / `firmware`) | `0x030000..0x23BC12` (сток) / `0x030000..0x7E0000` (OpenWrt) | До `7,872 КБ` (`8,060,928` Б) | 16-байтный заголовок `cvimg` (`cr6c` или `cs6c`) + 16-бит BE сумма `0x0000` | В стоке: ядро Linux 3.10.90 (`2,145,298` Б). В гибридной OpenWrt 4.14: объединённый образ `cs6c` (загрузчик LZMA + Linux 4.14.187 + DTB + `hsqsFAKE` @ `0x1B0000` + SquashFS @ `0x1B0284`). |
| `mtd3` (`rootfs`) | `0x23BC12..0x76CC14` (сток) / `0x1E0284` в флеш (OpenWrt) | `5,443,586` Б (сток) | `hsqs` (`0x73717368`) SquashFS 4.0 LE + 16-бит BE сумма `0x0000` | Корневая файловая система SquashFS 4.0 XZ (в стоке — нестандартный 12-байтный Tenda-XZ дескриптор; в OpenWrt — стандартный XZ). |
| `mtd4` (`cfg_primary`) | `0x7E0000..0x7F0000` | `64 КБ` (`65,536` Б) | `[0x00:0x04]` LE CRC32, `[0x04:0x08]` LE `seq_num` | Основной раздел настроек NVRAM Tenda (`CFM`). |
| `mtd5` (`cfg_backup`) | `0x7F0000..0x800000` | `64 КБ` (`65,536` Б) | `[0x00:0x04]` LE CRC32, `[0x04:0x08]` LE `seq_num - 1` | Резервный раздел настроек NVRAM Tenda (`CFM`). |
