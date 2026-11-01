# 02 — Реверс-инжиниринг загрузчика Realtek Booter v3.4.11B.9 и TFTP-прошивка / Bootloader RE & TFTP Recovery Guide

## 1. Полный дизассемблированный анализ `booter_stage2` (`v3.4.11B.9`, RAM `0x80000000`)

Загрузчик второго этапа распаковывается из GZIP-потока по смещению `0x007D60` в `mtd0` в оперативную память по адресу `0x80000000` (`102,496` байт):

| Смещение / Адрес RAM | Функция / Узел | Доказанное поведение в машинном коде MIPS32 (RU / EN) |
|---|---|---|
| `0x800068E8` | `eth_startup()` | Задаёт собственные сетевые параметры загрузчика: IP маршрутизатора **`192.168.1.6`** (`0xC0A80106`), ожидаемый IP TFTP-клиента ПК **`192.168.0.1`** (`0xC0A80101`), MAC загрузчика `56:AA:A5:5A:7D:E8`. |
| `0x8000F254` | `ip_input()` фильтр протокола | Выполняет `lbu $v0, 0x17($s0); li $a2, 0x11; bne $v0, $a2, drop` — **принимает ТОЛЬКО UDP (`0x11`), все ICMP Ping пакеты отбрасываются аппаратно/программно! Отсутствие пинга до `192.168.1.6` в режиме TFTP — это норма!** |
| `0x800060CC` | `check_image()` (Проверка при старте с флеш) | Ищет сигнатуру ядра `cr6c`/`cs6c` по смещениям флеш `0x020000`, `0x030000`, `0x040000`, `0x060000`, `0x080000` (начиная с `0x030000`), проверяет 16-битную BE сумму `== 0x0000`, затем ищет `hsqs` SquashFS и проверяет его 16-битную BE сумму `== 0x0000`. |
| `0x80006378` | `AutoBurn()` (Запись по TFTP `WRQ` на UDP порт 69) | Проверяет первые 4 байта полученного по TFTP файла: если это `cr6c` или `cs6c` и 16-битная BE сумма тела `== 0x0000`, берёт `burn_addr` напрямую из заголовка (`hdr[8..11] = 0x00030000`) и `len` (`hdr[12..15]`), стирает и записывает `len + 16` байт в SPI NOR Flash, затем **автоматически перезагружает роутер** (`Found *boot* image, Rebooting...`)! |
| `0x80005EFC` | Опрос кнопки Reset | Опрашивает **GPIO 54** (`GPIO Port G6`, регистр `0xB8003528` бит 22, активный `0`). При удержании кнопки Reset при включении питания переводит роутер в режим ожидания TFTP (`UDP:69`). |
| `0x80011898` | Защита от петли на WAN | Во время работы загрузчика принудительно отключает питание PHY **Порта 3 (WAN)** внешнего свитча `RTL8367RB-VB` (`PHY reg 0 = 0x1940`). **Подключать кабель ПК нужно ТОЛЬКО в порты LAN 1, LAN 2 или LAN 3!** |

---

## 2. Пошаговая инструкция по прошивке и восстановлению (RU)

### Способ А: Через штатный веб-интерфейс Tenda (без разборки и без TFTP)
1. Откройте веб-интерфейс роутера Tenda (`http://192.168.0.1` -> *Системные настройки* -> *Обновление ПО*).
2. Выберите файл **`tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`** (содержит проверенный 64-байтный заголовок `TRX2` с `model_version = 0x00030028` и `zlib.crc32`).
3. Дождитесь завершения загрузки и перезагрузки (~90 секунд). Роутер загрузит гибридную OpenWrt 4.14 (`http://192.168.0.1`).

### Способ Б: В 1 клик через загрузчик по TFTP (работает даже при повреждённой прошивке)
1. Подключите ПК патч-кордом в порт **LAN 1, LAN 2 или LAN 3** (не в WAN!).
2. Запустите от имени Администратора скрипт:
   - Для прошивки **Hybrid OpenWrt 4.14**: `offline_autonomous_tools\Flash_Hybrid_OpenWrt_4.14_TFTP.bat`
   - Для возврата на **оригинальный сток Tenda V15.03.06.23_multi**: `offline_autonomous_tools\Offline_TFTP_Recovery_and_Flash.bat`
3. Скрипт сам проверит контрольные суммы образа, сохранит текущие настройки вашей сетевой карты, временно выставит статический IP `192.168.1.1/24` и запустит TFTP-движок.
4. Зажмите кнопку **RST/WPS** на роутере, включите питание, удерживайте кнопку **5–7 секунд** и отпустите.
5. Скрипт автоматически определит ARP-ответ от `192.168.1.6`, передаст прошивку по `UDP:69` (`OCTET`), дождётся записи во флеш-память (`~45 секунд`) и автоматически вернёт вашу сетевую карту в режим DHCP!

---

## 3. Step-by-Step Flashing & Recovery Guide (EN)

### Method A: Direct Upload via Stock Tenda Web UI
1. Open the stock Tenda Web UI (`http://192.168.0.1` -> *System Settings* -> *Firmware Upgrade*).
2. Select **`tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`** (wrapped with the 64-byte `TRX2` header `0x00030028` verified against `libcommon.so`).
3. Wait ~90 seconds for flash write and automatic reboot into Hybrid OpenWrt 4.14 (`http://192.168.0.1`).

### Method B: 1-Click Bootloader TFTP Flash / De-Brick
1. Connect your PC via Ethernet cable to **LAN 1, LAN 2, or LAN 3** (never WAN Port 3, which is powered down by the bootloader!).
2. Right-click and **Run as Administrator**:
   - To flash **Hybrid OpenWrt 4.14**: `offline_autonomous_tools\Flash_Hybrid_OpenWrt_4.14_TFTP.bat`
   - To restore **Stock Tenda Firmware**: `offline_autonomous_tools\Offline_TFTP_Recovery_and_Flash.bat`
3. Hold the **RST/WPS** button on the router, plug in power, keep holding for **5–7 seconds**, then release.
4. The script automatically detects the bootloader at `192.168.1.6`, streams the verified `cs6c`/`cr6c` image to `UDP:69`, waits for flash programming + auto-reboot, and restores your PC's network adapter to DHCP.
