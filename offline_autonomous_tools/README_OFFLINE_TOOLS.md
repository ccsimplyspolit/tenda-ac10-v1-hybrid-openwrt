# Автономные скрипты прошивки, автонастройки и отката (RU / EN)

Все утилиты в этой папке написаны под чистую Windows 10 / 11 и работают **полностью без интернета**, без установки внешних пакетов `pip` и без включения дополнительного компонента Windows `tftp.exe`.

Главная защита от головной боли: каждый скрипт оборачивает смену сетевых настроек в жёсткий блок `try / finally` — даже если роутер долго перезагружается, вы случайно закрыли окно или нажали `Ctrl+C`, сетевая карта вашего компьютера автоматически вернётся на получение IP и DNS по DHCP.

---

## Быстрый справочник по батникам (RU) | One-Click Launchers (EN)

| Файл запуска | Что делает | Куда втыкать кабель и адрес |
|---|---|---|
| **`Flash_Hybrid_OpenWrt_4.14_TFTP.bat`** | Прошивает **Hybrid OpenWrt 4.14.187** (`tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin`) через загрузчик в 1 клик. Сам запрашивает права администратора, находит образ, открывает временное правило для UDP в брандмауэре, льёт прошивку на `192.168.1.6:69` и после старта роутера возвращает DHCP. | Строго жёлтый порт **LAN 1, LAN 2 или LAN 3** (синий WAN в загрузчике обесточен!) |
| **`Configure_OpenWrt_ISP_WAN_and_WiFi.bat`** | Переносит настройки провайдера и Wi-Fi в свежепрошитый OpenWrt за 10 секунд без интернета. Читает ваш стоковый бэкап `RouterCfm.cfg`, заходит по локальному SSH на `root@192.168.0.1` и прописывает клонированный WAN MAC, статику/DHCP WAN, DNS, имена и пароли Wi-Fi 2.4/5 ГГц и привязки IP. | Любой порт **LAN 1–3** (роутер уже загружен на `192.168.0.1`) |
| **`Offline_TFTP_Recovery_and_Flash.bat`** | Откатывает роутер обратно на чистую заводскую прошивку Tenda `V15.03.06.23` (`Tenda_AC10_V1_Stock_TFTP_Recovery.bin`) или заливает любой указанный образ с предварительной проверкой заголовка и контрольной суммы (опасные двухсегментные `cs6c+hsqs` блокируются до выхода в сеть). | Жёлтый порт **LAN 1, LAN 2 или LAN 3** (`192.168.1.6:69`) |
| **`Restore_Optimized_Config_and_WAN.bat`** | Заливает на стоковую прошивку профиль `Stock+` (`RouterCfm_optimized_v1.cfg` / `sanitized.cfg`): восстанавливает клонированный MAC, отключает облачного стукача `ucloud_v2`, убирает паразитный мост `br2` и расширяет таблицу сессий до `8192`. | `http://192.168.0.1` (на заводской прошивке Tenda) |
| **`Emergency_Restore_PC_Network_DHCP.bat`** | За 3 секунды снимает забытый статический IP (`192.168.1.x`) с физической сетевой карты ПК и включает автополучение IP/DNS по DHCP. | Локальная сетевая карта ПК (`Ethernet`) |
| **`Verify_All_Dumps_Chips_and_Backups.bat`** | Прогоняет 81 проверку целостности по локальным дампам, заголовкам образов и калибровкам `mtd1` (`xcap`, `RFE=6`). | Локальная проверка файлов |

---

## Как перенести настройки провайдера без интернета (`Configure_OpenWrt_ISP_WAN_and_WiFi.bat`)

У большинства кабельных провайдеров доступ в сеть жёстко привязан к MAC-адресу вашего роутера. После чистой установки OpenWrt роутер поднимается с заводским `HW_NIC0_ADDR + 2`, поэтому интернет не появится, пока не прописать старый MAC (и статический IP/шлюз, если у вас статика).

### Пошагово за минуту:
1. До прошивки сохраните файл настроек из родной веб-панели Tenda (*Системные настройки -> Резервная копия -> Сохранить*, получится файл `RouterCfm.cfg`) и положите его рядом со скриптами или в папку `backups\`.
2. Прошейте OpenWrt (`Flash_Hybrid_OpenWrt_4.14_TFTP.bat` или `webupgrade.bin` через браузер) и подождите **90–120 секунд**, пока роутер отформатирует раздел настроек `JFFS2` и выдаст вашему ПК адрес из `192.168.0.x`.
3. Вставьте кабель провайдера в синий порт **WAN**.
4. Дважды кликните **`Configure_OpenWrt_ISP_WAN_and_WiFi.bat`**.
5. Скрипт сам вытащит из `RouterCfm.cfg` ваш клонированный MAC, настройки WAN (DHCP или статику), DNS, ваши старые имена сетей Wi-Fi и пароли WPA2, аккуратно пропишет всё через `uci` по SSH (маскируя пароли звёздочками в окне консоли) и проверит, поднялся ли внешний линк.

### Ключи командной строки (если хотите задать параметры вручную без `RouterCfm.cfg`):
```powershell
powershell -ExecutionPolicy Bypass -File .\Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 `
  -WanMac "AA:BB:CC:DD:EE:FF" `
  -Ssid5G "MyHome_5G" -Key5G "MyStrongPass123" `
  -Ssid2G "MyHome_2G" -Key2G "MyStrongPass123"
```

Поддерживаемые флаги `Configure_OpenWrt_ISP_WAN_and_WiFi.ps1`:
- `-ConfigPath <путь>` — путь к вашему `RouterCfm.cfg` (по умолчанию ищется автоматически).
- `-TargetIp <IP>` — адрес роутера (по умолчанию `192.168.0.1`).
- `-WanMac <XX:XX:XX:XX:XX:XX>` — явно задать клонированный MAC на интерфейс WAN.
- `-Ssid5G` / `-Key5G` / `-Ssid2G` / `-Key2G` — явно задать имена и пароли сетей Wi-Fi (минимум 8 символов).
- `-VerifyOnly` — только проверить чтение `RouterCfm.cfg`, ничего не отправляя по сети.
- `-DryRun` — показать сгенерированные команды `uci` на экране без подключения по SSH.

---

## English Quick Reference (`Configure_OpenWrt_ISP_WAN_and_WiFi.ps1` & TFTP Suite)

1. **Flash Hybrid OpenWrt 4.14.187 in 1 click:** Connect Ethernet to **LAN 1–3** (never blue WAN — bootloader powers down Switch Port 3 PHY at `0x8000ED48`), run **`Flash_Hybrid_OpenWrt_4.14_TFTP.bat`**, hold **RST/WPS** while plugging in 12V power for **7–10 seconds**, then release. Do not wait for `ping 192.168.1.6` — Realtek Booter drops all non-UDP packets at `0x80001010`; our Python TFTP engine (`tftp_recovery_engine.py`) probes ARP + UDP port 69 directly.
2. **Migrate ISP WAN MAC & Wi-Fi offline:** Once OpenWrt boots at `192.168.0.1`, double-click **`Configure_OpenWrt_ISP_WAN_and_WiFi.bat`**. It parses your saved Tenda `RouterCfm.cfg` locally and provisions cloned WAN MAC, DHCP/static WAN IP, DNS, static DHCP leases, and 2.4/5 GHz Wi-Fi credentials over built-in Windows `ssh.exe` while masking secrets in console output.
3. **Run the offline loopback self-tests (40 checks, zero hardware required):**
   ```powershell
   python -B .\Test_Offline_Autonomous_Tools_Loopback.py
   ```
