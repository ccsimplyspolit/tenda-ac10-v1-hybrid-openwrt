# Release v4.14.187-r2-ac10-hybrid — Проверенная сборка Hybrid OpenWrt 4.14.187 для Tenda AC10 V1.0 (RU / EN)

> ⚠️ **ТОЛЬКО ДЛЯ Tenda AC10 V1.0 (`Ver: V1.0`, сток `V15.03.06.xx`, FCC `V7TAC10`, 8 MB Flash / 64 MB RAM)!**  
> **НЕ ШЕЙТЕ на ревизии V2.0 и V3.0 (`RTL8197FH`, eCos, 2 MB Flash)** — получите мгновенный кирпич с затёртым загрузчиком!

- **Документация и скриншоты:** https://ccsimplyspolit.github.io/tenda-ac10-v1-hybrid-openwrt/
- **Двуязычная Wiki (RU / EN):** https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/wiki
- **Гайд и обсуждение на 4PDA (#3585):** https://4pda.to/forum/index.php?showtopic=885989&view=findpost&p=145799909

---

## Что внутри сборки `r2` (RU) | What's Fixed Out of the Box (EN)

Эта ревизия собрана после боевой обкатки на живом Tenda AC10 V1.0 под домашним провайдером с привязкой по MAC-адресу. Все 14 найденных болячек железа и сети уже вшиты прямо в образ — ничего допиливать напильником по SSH после прошивки не нужно:

1. **Стабильный 5 ГГц Wi-Fi (`RTL8822BE` + внешние усилители `Skyworth SE5003L1` RFE Type 6):**
   - Устранён провал мощности `-17 dB` из-за пустого заводского OTP eFuse (`0xFF`) + автоматическая подгрузка родной подстройки кварца `XCAP` и MAC из `/dev/mtd1` скриптом `/bin/set-mib.sh`.
   - По умолчанию выставлен проверенный профиль **`VHT20`, канал `36`, `23 dBm` (200 мВт)** с жёсткой привязкой `ifname='wlan1'` по пути PCIe — ноль обрывов связи (в отличие от `VHT80`, где чип B-cut периодически ловил таймауты регистра `0x33`; при желании `VHT40`/`VHT80` переключаются в меню LuCI).
2. **Работает и кабель, и Wi-Fi одновременно без «чёрной дыры» (`hwnat=0` + Software Flow Offloading):**
   - Включён `flow_offloading='1'` при `hwnat=0` и аппаратном режиме свитча `role='router'` (`fabric_autoreset=3`). Это убирает классический баг чипсета, когда по кабелю летит гигабит, а на телефонах по Wi-Fi висит «Подключено, без доступа к интернету». Скорость из коробки — **~350–500 Мбит/с** по проводу и воздуху одновременно (а для чисто проводного гигабита `echo 1 > /sys/module/rtl819x/parameters/hwnat` даёт полные **940 Мбит/с** при 0.5% CPU).
3. **Клонированный MAC провайдера не слетает после выключения из розетки (`wait_netif_mac`):**
   - Стартовый скрипт `dir842-asic` теперь дожидается применения клонированного `network.wan.macaddr` на `eth0.1` перед программированием таблиц маршрутизации `gw_prog`.
4. **Никакой ругани на DNS от iPhone и Mac (RFC 9462 DDR + чистый IPv4):**
   - Вычищен локальный `ula_prefix` IPv6 и настроен `dhcp_option '6,1.1.1.1,8.8.8.8,192.168.0.1'` — iOS сразу включает шифрованный DoH по HTTP/3 QUIC и больше не пугает жёлтой плашкой «Эта сеть блокирует защищенный трафик DNS».
5. **Закрытые сокеты со стороны провайдера и сохранение настроек с первого старта:**
   - `uhttpd` слушает только `192.168.0.1:80`, `dnsmasq` отключён от `eth0.1`, а скрипт `80_mount_root` при первом запуске сам очищает мусор стока в `mtd5` под чистый `JFFS2`.
6. **Готовые офлайн-скрипты в архиве `Tenda_AC10_V1_Offline_Autonomous_Toolkit.zip`:**
   - `Flash_Hybrid_OpenWrt_4.14_TFTP.bat` — прошивка по TFTP в 1 клик с автовозвратом DHCP на сетевой карте ПК;
   - `Configure_OpenWrt_ISP_WAN_and_WiFi.bat` — перенос клонированного MAC провайдера, настроек WAN и ваших сетей Wi-Fi из стокового `RouterCfm.cfg` за 10 секунд без интернета;
   - `Offline_TFTP_Recovery_and_Flash.bat` — быстрый откат на чистый сток Tenda `V15.03.06.23`.

> **Честное примечание по 2.4 ГГц:** диапазон 5 ГГц лупит на полные 23 dBm, а для 2.4 ГГц пока используется готовый модуль `rtl8192cd.ko` от DIR-842 R1 без калибровочных таблиц усилителя `SKY85303-11` — вблизи роутера он работает нормально, но как основную сеть лучше использовать 5 ГГц.

---

## Какой файл скачивать | Which File to Download

| Файл | Размер | Для чего нужен |
|---|---:|---|
| **`tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`** | `5,546,694` Б | **Прямая прошивка через браузер из родного меню Tenda** (`192.168.0.1` -> Обновление ПО, без ошибки `"Format error!"`). |
| **`tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin`** | `5,546,630` Б | **Прошивка в 1 клик по TFTP и раскирпичивание** через загрузчик (`192.168.1.6:69`, безопасный односегментный `cs6c`). |
| **`tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin`** | `5,546,630` Б | Обновление поверх уже установленной OpenWrt (через LuCI или `sysupgrade`). |
| **`Tenda_AC10_V1_Offline_Autonomous_Toolkit.zip`** | `73,348` Б | Все `.bat` / `.ps1` / `.py` скрипты автопрошивки, переноса настроек провайдера из `RouterCfm.cfg` и восстановления сети ПК. |
| **`Tenda_AC10_V1_Build_and_Router_Scripts.zip`** | `32,794` Б | Сборочный скрипт `build_hybrid_openwrt_ac10.sh`, `set-mib.sh`, `tenda-ac10-v1.dts`, конфиг ядра и утилита `mtd1`. |
| **`Tenda_AC10_V1_Stock_TFTP_Recovery.bin`** | `7,588,884` Б | Чистая заводская прошивка Tenda `V15.03.06.23` для отката обратно на сток по TFTP. |

## Контрольные суммы | SHA-256 Checksums

```text
5954e788b577597c5fe1bd23e18158fb5e368226bf3bc69fca7e0b18cd77ad76  tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
5954e788b577597c5fe1bd23e18158fb5e368226bf3bc69fca7e0b18cd77ad76  tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin
87da99ea1df7312b41e26e3f9fa449a7863427e7b84a50790a0727694583e056  tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin
f5c7d1755689dd5319420289d8ebd4e661d418f56d99b775f6111c48a3c96345  tenda-ac10-v1.dtb
a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa  Tenda_AC10_V1_Stock_TFTP_Recovery.bin
edeb3fb6d6834da5baf8aa9e05379f8e9c47f980b090e3d6e4d6bef251527e81  Tenda_AC10_V1_Offline_Autonomous_Toolkit.zip
5453f796c5a00e1154ab9327e6ca03f4dd514154233d940c39e3f70b82243c1a  Tenda_AC10_V1_Build_and_Router_Scripts.zip
```
