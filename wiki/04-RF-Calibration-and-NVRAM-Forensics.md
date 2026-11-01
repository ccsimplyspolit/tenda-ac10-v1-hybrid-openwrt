# 04 — Заводская RF-калибровка (mtd1, 40 ключей, EFUSE) и оптимизация NVRAM / RF Calibration, EFUSE Map & CFM NVRAM Forensics

## 1. Структура раздела `/dev/mtd1` (`0x020000..0x030000`)

Раздел `mtd1` (`setting`, 64 КБ) имеет 8-байтный заголовок:
- `[0x00:0x04]`: 32-битный Little-Endian IEEE 802.3 CRC32 (`zlib.crc32(mtd1[8:]) = 0xDEED2A7D`)
- `[0x04:0x08]`: `0x00000000`
- `[0x08:0x10000]`: 40 ASCII-строк `KEY=VALUE`, разделённых нулевыми байтами `\x00`.

### Как калибровка применяется в Гибридной OpenWrt 4.14:
1. **При загрузке (`/etc/init.d/ac10-hwparams` -> `/bin/set-mib.sh`)**:
   - Читает все 40 ключей напрямую из `/dev/mtd1` с проверкой регулярными выражениями и безопасными фолбэками.
   - Настраивает параметры 2.4 ГГц (`wlan0`) и 5 ГГц (`wlan1`), включая `XCAP`, `THER`, `RFE_TYPE` (`5` для 2.4G, `6` для 5G), по-канальные таблицы мощности (`pwrlevelCCK_A/B`, `pwrlevelHT40_1S_A/B`, `pwrlevel5GHT40_1S_A/B`) и смещения (`pwrdiff*`), а также синтезирует 512-байтную карту виртуального EFUSE `RTL8822BE` (`/tmp/rtl8822be_efuse.bin`) в соответствии с функцией `halmac_parse_efuse_data_88xx` (`0x802FE788`).
2. **В модуле `rtw88_core` (`/etc/modules.d/rtw88`)**:
   - Передаётся параметр `rtw88_core xtal_cap_override=27` (`HW_WLAN0_11N_XCAP=27` = `0x1B`), который записывает точное значение заводской ёмкости кварца 5 ГГц в регистр `REG_AFE_XTAL_CTRL` (`0x0024` / `0x1028`) чипа `RTL8822BE`.
3. **В netifd-скрипте `/lib/netifd/wireless/rtl8192cd.sh`**:
   - При генерации `/etc/Wireless/RTL8192CD.dat` автоматически читает из `/dev/mtd1` параметры `HW_WLAN1_*` и записывает `wlan0_rfe_type=5`, `wlan0_xcap=46`, `wlan0_ther=32` и все 7 шестнадцатеричных таблиц мощности 2.4 ГГц.

---

## 2. Карта 512-байтного виртуального EFUSE `RTL8822BE` (`halmac_parse_efuse_data_88xx`)

| Диапазон смещений EFUSE | Ключ в `/dev/mtd1` | Длина | Описание (RU / EN) |
|---|---|---|---|
| `0x010..0x0AF` | `HW_WLAN0_TX_POWER_5G_*` | 160 Б | По-базовые таблицы мощности и дифференциалы BW20/40/80/160 для Пути A и Пути B. |
| `0x0B8` | `HW_WLAN0_REG_DOMAIN` (`1`) | 1 Б | Код регуляторного домена (`FCC = 0x01`). |
| `0x0B9` | `HW_WLAN0_11N_XCAP` (`27`) | 1 Б | Кварцевый конденсатор `CrystalCap` (`0x1B`). |
| `0x0BA` | `HW_WLAN0_11N_THER` (`32`) | 1 Б | База термодатчика `ThermalMeter` (`0x20`). |
| `0x0CA` | `HW_WLAN0_RF_TYPE` (`6`) | 1 Б | Селектор внешнего FEM Skyworth `SE5003L1` (`RFE Type 6`). |
| `0x11A..0x11F` | `HW_WLAN0_WLAN_ADDR` | 6 Б | MAC-адрес радиомодуля 5 ГГц PCIe. |

---

## 3. Оптимизация стокового NVRAM (`RouterCfm_optimized_template.cfg`)

В папке [`01_Stock_Firmware_and_Partitions/RouterCfm_optimized_template.cfg`](../01_Stock_Firmware_and_Partitions/RouterCfm_optimized_template.cfg) представлен очищенный от персональных данных шаблон оптимизированной конфигурации стоковой прошивки:
- Отключены фоновые облачные демоны Tenda (`cloud_kill=1`, `uc_enable=0`), вызывавшие утечки сокетов и нагрузку на CPU.
- Исправлены адреса NTP-серверов (`time.cloudflare.com`, `time.google.com`) вместо заблокированных в прошивке серверов.
- Включены `Beamforming+`, `LDPC`, `STBC`, `Short GI`, `VHT80` (5 ГГц) и `20/40 МГц` (2.4 ГГц).
