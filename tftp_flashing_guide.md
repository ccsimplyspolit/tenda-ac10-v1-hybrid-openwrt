# TFTP Flashing & Unbrick Guide: Tenda AC10 V1.0 (RU / EN)

Если роутер не грузится после чужой сборки, мигнул свет во время обновления или вы просто хотите начисто залить **Hybrid OpenWrt 4.14.187** либо вернуться на заводской сток — паяльник и программатор не нужны. В первых 128 КБ флешки (`mtd0`, `0x000000..0x020000`) сидит нестираемый загрузчик **Realtek Booter v3.4.11B.9**, который поднимает роутер по кабелю за пару минут.

> **Самый простой путь:** запустите готовый батник из папки [`offline_autonomous_tools/`](offline_autonomous_tools/):
> - **`Flash_Hybrid_OpenWrt_4.14_TFTP.bat`** — залить Hybrid OpenWrt 4.14.187 (`factory.bin`).
> - **`Offline_TFTP_Recovery_and_Flash.bat`** — откатиться на чистый заводской сток Tenda (`V15.03.06.23`).
> Они сами проверят контрольную сумму образа, выставят временную статику на сетевой карте и в конце вернут обратно DHCP.

---

## 1. Три железных правила загрузчика Realtek (почему у многих «не шьётся»)

Мы разобрали бинарник `booter_stage2_v3.4.11B.9` в дизассемблере, и вот почему классические инструкции из интернета вводят людей в ступор:

1. **`ping 192.168.1.6` никогда не ответит — даже не ждите его.**  
   На адресе `0x80001010` входной парсер загрузчика проверяет заголовок IPv4: если протокол не равен `0x11` (`UDP`), пакет молча выбрасывается. Кода для ответа на `ICMP Ping` в загрузчике физически нет. Зато он исправно отвечает на ARP (`50:0F:F5:00:00:01`) и сразу принимает файл по `UDP:69`.
2. **Синий порт WAN в режиме восстановления полностью обесточен.**  
   При старте загрузчик вызывает `rtk_port_phy_power_down(3)` (`0x8000ED48`) и гасит физический приёмопередатчик синего разъёма WAN. Кабель от ПК нужно втыкать **строго в жёлтые порты LAN 1, LAN 2 или LAN 3**.
3. **Нельзя лить самодельные двухсегментные образы `cs6c` + `hsqs`.**  
   В функции `AutoBurn` на адресе `0x80001C2C` сидит заводской баг слота задержки ветвления (`move $s7, $s2` при `$s2 = 0`): если в файле идут подряд два сегмента с магией `cs6c`, второй кусок пишется прямо по адресу `0x00000000` поверх самого загрузчика. Наш `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin` упакован строго **одним монолитным сегментом `cs6c`** с записью на `0x00030000`, поэтому загрузчик (`mtd0`) и заводские калибровки (`mtd1`) в полной безопасности.

---

## 2. Прошивка или откат в 1 клик на Windows (рекомендуется)

1. Вставьте патч-корд от компьютера в **LAN 1, LAN 2 или LAN 3** роутера.
2. Запустите двойным кликом **`offline_autonomous_tools\Flash_Hybrid_OpenWrt_4.14_TFTP.bat`** (для OpenWrt) или **`offline_autonomous_tools\Offline_TFTP_Recovery_and_Flash.bat`** (для отката на сток) и подтвердите запрос прав Администратора.
3. Переведите роутер в режим ожидания прошивки:
   - Выдерните штекер питания 12V.
   - Зажмите скрепкой утопленную кнопку **RST/WPS** сзади.
   - Удерживая кнопку, вставьте питание обратно и держите **7–12 секунд**, пока индикатор `SYS` не замигает, затем отпустите.
4. Скрипт поймает загрузчик по ARP, передаст все блоки на `192.168.1.6:69` (около 7 секунд), подождёт ~60–90 секунд, пока флешка перезапишется и сработает аппаратный Watchdog, и сам переключит сетевую карту ПК обратно в DHCP.
5. Откройте `http://192.168.0.1` (при первом старте OpenWrt дайте ему до полутора минут на разметку чистого раздела настроек `JFFS2`).
6. Если сбили настройки провайдера — запустите **`offline_autonomous_tools\Configure_OpenWrt_ISP_WAN_and_WiFi.bat`** (для OpenWrt) или **`Restore_Optimized_Config_and_WAN.bat`** (для стока). А если прервали скрипт вручную и осталась статика — кликните **`Emergency_Restore_PC_Network_DHCP.bat`**.

---

## 3. Ручная прошивка без скриптов (Windows CMD / Tftpd64 / Linux)

If you prefer flashing manually without helper scripts (`EN / RU`):

1. Plug Ethernet into **LAN 1, LAN 2, or LAN 3** (never WAN) and set static IPv4 on your PC:
   - IP: `192.168.1.100`, Mask: `255.255.255.0`, Gateway: `192.168.1.6`
2. Hold **RST/WPS**, plug in 12V power, hold for **10 seconds**, release.
3. Push `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin` (or `Tenda_AC10_V1_Stock_TFTP_Recovery.bin`) directly to `192.168.1.6`:
   - **Windows CMD:**
     ```cmd
     tftp -i 192.168.1.6 PUT tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
     ```
   - **Linux / macOS:**
     ```bash
     curl -T tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin tftp://192.168.1.6/firmware.bin
     ```
   - **Tftpd64 GUI:** Select adapter `192.168.1.100`, open **Tftp Client** tab, set Host `192.168.1.6`, Port `69`, pick `factory.bin`, click **Put**.
4. Wait ~90 seconds without cutting power until the router reboots on its own, switch your PC NIC back to automatic DHCP, and open `http://192.168.0.1`.

---

## 4. Консоль UART и программатор CH341A (на крайний случай)

- **3.3V UART (115200 8N1):** 4-контактная гребёнка на плате: `Pin 1` (квадратный) = `3.3V` (**не подключать!**), `Pin 2` = `TX`, `Pin 3` = `RX`, `Pin 4` = `GND`. Нажатие `ESC` при подаче питания открывает консоль `<RealTek>`.
- **Программатор SPI NOR (`CH341A` + прищепка SOIC-8 3.3V):** микросхема **Winbond W25Q64FV / W25Q64JV** (`JEDEC 0xEF4017`, ровно `8,388,608` байт). Эталонные разделы `mtd0` (`bootloader`) и очищенный шаблон `mtd1` лежат в папке [`01_Stock_Firmware_and_Partitions/`](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/tree/main/01_Stock_Firmware_and_Partitions).
