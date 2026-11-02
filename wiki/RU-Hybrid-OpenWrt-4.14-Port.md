# Hybrid OpenWrt 4.14.187 для Tenda AC10 V1.0: устройство, скриншоты и автонастройка

> **Навигация:** [Главная (RU)](RU-Home) | [English Version](EN-Hybrid-OpenWrt-4.14-Port) | [Wiki Portal](Home)

Сборка **Hybrid OpenWrt 4.14.187 (`v4.14.187-r3-ac10-hybrid`)** совмещает привычное пользовательское окружение **OpenWrt 19.07 + LuCI** (`http://192.168.0.1`, SSH Dropbear, `fw3`, сохранение настроек в `JFFS2`) с пропатченным ядром **Linux 4.14.187** под процессор `RTL8197FS`, свитч `RTL8367RB` и радиомодуль 5 ГГц `RTL8822BE`.

---

## 1. Живая панель LuCI после прошивки

| Сводка (`Status -> Overview`) | Wi-Fi 5 ГГц `23 dBm` (`Network -> Wireless`) |
|---|---|
| ![Overview](https://raw.githubusercontent.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/main/docs/images/01_luci_status_overview.png) | ![Wireless](https://raw.githubusercontent.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/main/docs/images/02_luci_wireless_5ghz.png) |

| Коммутатор `RTL8367RB` (`Network -> Switch`) | Flow Offloading (`Network -> Firewall`) |
|---|---|
| ![Switch](https://raw.githubusercontent.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/main/docs/images/04_luci_switch_vlans.png) | ![Firewall](https://raw.githubusercontent.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/main/docs/images/05_luci_firewall_offload.png) |

---

## 2. Что реально сделано и починено в сборке `r3` (`v4.14.187-r3-ac10-hybrid`)

1. **Wi-Fi 5 ГГц `RTL8822BE`: полная скорость `VHT80` (80 МГц) и усилители `Skyworth SE5003L1` (`RFE Type 6`):**
   - На заводе в чипе не прожгли память OTP eFuse (сплошные `0xFF`). Мы пропатчили ELF-релокации модуля `rtw88_8822b.ko` под `RFE Type 6` (`0x82C/0x830/0x838/0x83C`), а скрипт `/bin/set-mib.sh` при каждом старте считывает из `/dev/mtd1` родную ёмкость кварца `HW_WLAN0_11N_XCAP` и заводской MAC.
   - В ревизии r3 таймаут опроса RF-регистра 0x33 увеличен со 100 до 1000 циклов (2 мс) на смещениях `.text+0x2EDC` и `.text+0x2F7C`, активирован порог CCA в регистре `REG_L1WT` (`0x9194b2b9`), а в `rtw88_core.ko` передача служебных и EAPOL-кадров зафиксирована на `DESC_RATE6M` (`0x04`).
   - По умолчанию выставлен скоростной стабильный профиль **`VHT80` (80 МГц), канал `36`, `23 dBm` (200 мВт)** — линк держит до 866.7 Мбит/с PHY без единого отвала под непрерывной нагрузкой.
2. **Одновременная работа аппаратного NAT (940 Мбит/с) и Wi-Fi без «чёрной дыры» (`SWTCR0 |= 0x400C` / `WANRouteMode=ToCpu`):**
   - В шлюз ядра `gw_prog` внедрён патч `WANRouteMode=ToCpu` совместно со сбросом `dir842-l2flush`. Теперь аппаратный NAT (`hwnat=1`) выдаёт честные `940 Мбит/с` по кабелю при нагрузке на процессор всего 0.5%, и одновременно все клиенты по Wi-Fi передают трафик на предельной скорости без малейших потерь.
3. **Wi-Fi 2.4 ГГц: полная заводская калибровка `Skyworks SKY85303-11` из `mtd1`:**
   - Скрипт `/bin/set-mib.sh` при загрузке динамически считывает из `/dev/mtd1` индивидуальные калибровки мощности (CCK, HT40), термокомпенсации (`ther`), кварца (`xcap`), региона (`regdomain`) и антенных переключателей (`trswitch`), а также включает аппаратную агрегацию `ampdu=1` + `amsdu=1` и отключает сбойный `disable_txsc=1`. Сеть 2.4 ГГц обеспечивает полное покрытие на всей мощности.
4. **Асимметричный Flow Control и двухуровневый сторож зависаний:**
   - Включен асимметричный контроль потока RGMII `trunk_pause=3` (`PCRP0[17:16]=1`, `EXT1 0x1311 |= 0x0020 FORCE_RXPAUSE`), увеличены буферы `SBFCR1` (`FCOFF=320, FCON=380`), а сторож зависаний `rtl819x_hang_check` Stage 1 выполняет мягкий слив FIFO (<2 мс) без обрыва сетевых сессий.
5. **Клонированный MAC провайдера не отваливается после ребута по питанию:**
   - В `/etc/init.d/dir842-asic` функция `wait_netif_mac()` теперь ждёт не только `eth0.2` (LAN), но и применения клонированного `network.wan.macaddr` на `eth0.1` перед вызовом `gw_prog`.
6. **Правильная распиновка нечётного порта WAN (`Port 3`) и `GPIO 58`:**
   - В `tenda-ac10-v1.dts` прописан сброс свитча `<&gpio1 26 GPIO_ACTIVE_LOW>` (`GPIO 58`), а в `vmlinux` внесены MIPS32 патчи под нечётный `Port 3` WAN (включая сдвиг верхних 16 бит регистра PVID).
7. **Чистый DoH на iPhone / Mac (RFC 9462 DDR) и изоляция WAN:**
   - Убран `ula_prefix`, выставлен `dhcp_option '6,1.1.1.1,8.8.8.8,192.168.0.1'` — iOS сразу уходит на HTTP/3 DoH без жёлтого предупреждения о блокировке DNS. Службы `uhttpd` и `dnsmasq` закрыты от внешнего интерфейса `eth0.1`.

---

## 3. Прошивка и перенос настроек провайдера в 1 клик

В релизе лежат три образа и архив готовых скриптов `Tenda_AC10_V1_Offline_Autonomous_Toolkit.zip`:

| Файл | Назначение |
|---|---|
| **`tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`** | Прямая прошивка из заводского веб-меню Tenda (`192.168.0.1` -> Обновление ПО, с шапкой `trx2` `0x00030028`). |
| **`tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin`** | Прошивка и раскирпичивание по TFTP через загрузчик (`192.168.1.6:69`, односегментный `cs6c`, защищён от бага `$s7=0`). |
| **`tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin`** | Обновление поверх работающей OpenWrt через LuCI или `sysupgrade`. |

### Быстрый сценарий с автопереносом настроек провайдера:
1. Сохраните со стоковой прошивки резервную копию настроек `RouterCfm.cfg`.
2. Прошейте роутер через браузер (`webupgrade.bin`) или запустите от имени Администратора **`offline_autonomous_tools\Flash_Hybrid_OpenWrt_4.14_TFTP.bat`** (кабель строго в **LAN 1–3**, зажать `RST/WPS` при включении питания на 7–10 с).
3. Подождите **90–120 секунд** при первом включении (скрипт `80_mount_root` отформатирует чистый раздел `JFFS2`).
4. Вставьте кабель провайдера в синий порт **WAN** и запустите **`offline_autonomous_tools\Configure_OpenWrt_ISP_WAN_and_WiFi.bat`** — скрипт за 10 секунд перенесёт из `RouterCfm.cfg` клонированный MAC, настройки WAN, DNS, статические привязки DHCP и ваши сети Wi-Fi.
