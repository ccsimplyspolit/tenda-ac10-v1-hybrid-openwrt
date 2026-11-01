# Оригинальная заводская прошивка и разделы SPI NOR Flash Tenda AC10 V1.0 / Stock Firmware & Flash Partitions

Все файлы в этой директории проверены по контрольным суммам и **полностью очищены от персональных паролей и личных MAC-адресов** (готовы для публичного использования и восстановления любого экземпляра Tenda AC10 V1.0):

| Файл / Filename | Размер / Size | Описание (RU) / Description (EN) |
|---|---|---|
| `Tenda_AC10_V1_Stock_TFTP_Recovery.bin` | `7,588,884` B | Полный двухсегментный стоковый образ Tenda `V15.03.06.23_multi` (`mtd2` ядро `cr6c` + `mtd3` `hsqs` SquashFS) для восстановления стока через загрузчик по TFTP (`0x030000..0x76CC14`). Не содержит личного NVRAM (`mtd4`/`mtd5`). |
| `mtd0_bootloader_0x000000_128KB.bin` | `131,072` B | Раздел загрузчика `mtd0` (`0x000000..0x020000`): Stage-1 DDR2 init + сжатый GZIP по смещению `0x7D60` Stage-2 загрузчик **Realtek Booter v3.4.11B.9**. |
| `booter_stage2_v3.4.11B.9_0x80000000.bin` | `102,496` B | Распакованный бинарный образ загрузчика **Realtek Booter v3.4.11B.9** (адрес загрузки в RAM `0x80000000`). |
| `mtd1_factory_cfg_rf_cal_0x020000_64KB_sanitized.bin` | `65,536` B | Эталонный дамп заводской RF-калибровки `mtd1` (`0x020000..0x030000`) с пересчитанным CRC32 и шаблонными MAC-адресами `50:0F:F5:00:00:00..05` (все 35 таблиц калибровки 2.4G/5G сохранены 1:1). |
| `mtd1_factory_rf_cal_40keys_sanitized.json` | `2,584` B | Все 40 ключей калибровки `mtd1` в формате JSON. |
| `kernel_cr6c_0x030000.bin` | `2,145,298` B | Стоковое ядро Linux 3.10.90 (`cr6c`, `start=0x80000000`, `burn=0x00030000`, 16-bit BE csum `0x0000`). |
| `rootfs_squashfs_tenda_xz_0x23BC12.bin` | `5,443,586` B | Стоковая файловая система SquashFS 4.0 с нестандартным 12-байтным Tenda-XZ заголовком (`0x23BC12..0x76CC14`). |
| `kallsyms_stock_31434.txt` | `1,042,358` B | Полная таблица из 31,434 символов ядра `vmlinux` стоковой прошивки Linux 3.10.90. |
| `RouterCfm_optimized_template.cfg` | `25,382` B | Шаблон оптимизированной конфигурации стоковой прошивки (отключена облачная телеметрия `cloud_kill=1`, `uc_enable=0`, настроены Cloudflare/Google NTP, включены Beamforming+, VHT80, LDPC, STBC). Замените плейсхолдеры `<YOUR_PASSWORD_MD5>`, `<YOUR_WIFI_PASSWORD>`, `<YOUR_WAN_MAC>` перед импортом. |
