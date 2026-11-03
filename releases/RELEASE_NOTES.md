# Release v4.14.187-r3-ac10-hybrid — Финальная откалиброванная сборка Hybrid OpenWrt 4.14.187 (r3) для Tenda AC10 V1.0 (RU / EN)

> ⚠️ **ТОЛЬКО ДЛЯ Tenda AC10 V1.0 (`Ver: V1.0`, сток `V15.03.06.xx`, FCC `V7TAC10`, 8 MB Flash / 64 MB RAM)!**  
> **НЕ ШЕЙТЕ на ревизии V2.0 и V3.0 (`RTL8197FH`, eCos, 2 MB Flash)** — получите мгновенный кирпич с затёртым загрузчиком!

- **Документация и скриншоты:** https://ccsimplyspolit.github.io/tenda-ac10-v1-hybrid-openwrt/
- **Двуязычная Wiki (RU / EN):** https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/wiki
- **Гайд и обсуждение на 4PDA (#3585):** https://4pda.to/forum/index.php?showtopic=885989&view=findpost&p=145799909

---

## Что нового в финальной ревизии `r3` (RU) | What's New in `r3` Out of the Box (EN)

В ревизии **`v4.14.187-r3-ac10-hybrid`** полностью устранены все ограничения ранних сборок (`VHT20`, слабая мощность 2.4 ГГц, микро-сбросы `SIRR FULL_RST` под нагрузкой 2000+ МБ и конфликт `hwnat=1` с Wi-Fi):

1. **Полноскоростной 5 ГГц Wi-Fi `VHT80` (80 МГц, до 866.7 Мбит/с PHY, 200–450+ Мбит/с реальных) на `RTL8822BE` + `Skyworth SE5003L1` (`RFE Type 6`):**
   - В `rtw88_8822b.ko` время ожидания калибровки RF-регистра `0x33` увеличено в 10 раз (`100 -> 1000` итераций / `2 мс`) как для 1x1 SISO (`.text+0x2EDC`), так и для 2x2 MIMO (`.text+0x2F7C`), а для `Cut-B` + `RFE Type 6` активирован регистр порогов вторичных подканалов CCA `REG_L1WT` (`0x9194b2b9`).
   - В `rtw88_core.ko` (`rtw_tx_pkt_info_update`) принудительно выставлена скорость `DESC_RATE6M` (`6 Мбит/с OFDM`, `0x04`) вместо невалидной в 5 ГГц `DESC_RATE1M` (`1 Мбит/с CCK`) для всех управляющих и EAPOL-кадров — смартфоны и ноутбуки мгновенно проходят 4-way WPA2-рукопожатие на ширине **80 МГц (`VHT80`)**.
2. **Полная заводская калибровка 2.4 ГГц (`RTL8197FS` + `Skyworks SKY85303-11` RFE Type 5):**
   - Скрипт `/bin/set-mib.sh` динамически находит раздел `calibration` (`/dev/mtd1`), выгружает индивидуальные таблицы мощности `pwrlevelCCK_A/B`, `pwrlevelHT40_1S_A/B`, `ther`, `xcap`, `regdomain` и `trswitch`, включает аппаратную агрегацию `ampdu=1` + `amsdu=1` и отключает сбойный TX-shortcut (`disable_txsc=1`).
3. **Аппаратное ускорение `hwnat=1` + `ToCpu` и ликвидация `FABRIC WEDGE` (`SIRR FULL_RST`) под нагрузкой 2000+ МБ:**
   - В ядро `vmlinux` внесено **34 выверенных бинарных патча MIPS32 LE**: включён бит `WANRouteMode=ToCpu` (`SWTCR0 |= 0x400C`) в `gw_prog` (совместная работа `hwnat=1` и Wi-Fi без «чёрной дыры»), настроены повышенные пороги буфера `SBFCR1` (`320/380`), включён асимметричный контроль потока `trunk_pause=3` между `RTL8367RB` и `RTL8197F`, а сторожевой таймер `rtl819x_hang_check` переведён на мягкую двухступенчатую очистку FIFO без разрушительного сброса `SIRR FULL_RST`.
   - Событийный демон `/etc/init.d/dir842-l2flush` сбрасывает устаревшие записи L2 только при реальной смене линка/FDB.
4. **Идеальная работа с Apple iPhone / Mac (RFC 9462 DDR) и жёсткая защита WAN:**
   - Вычищен локальный `ula_prefix` IPv6, настроен `dhcp_option '6,1.1.1.1,8.8.8.8,192.168.0.1'` (мгновенный HTTP/3 DoH без предупреждений iOS), закрыты внешние сокеты `uhttpd`/`dnsmasq` со стороны провайдера, а уязвимый протокол WPS полностью отключён.
5. **Поддержка любого IP-адреса LAN и режима точки доступа (Dumb AP / Bridge) без потери LuCI (Issue #1 fix):**
   - Сервер `uhttpd` переведён на прослушивание `0.0.0.0:80` и `[::]:80` с фильтром `rfc1918_filter='1'`, а в брандмауэре добавлено явное правило `Block-WAN-HTTP` и запрет в `/etc/firewall.user` (`iptables/ip6tables -I INPUT -i eth0.1 -p tcp --dport 80 -j DROP`). Веб-интерфейс LuCI остаётся доступным при любой смене подсети LAN и в режиме моста (`proto=dhcp`), при этом WAN-интерфейс со стороны провайдера остаётся полностью изолированным.

---

## Какой файл скачивать | Which File to Download

| Файл | Размер | Для чего нужен |
|---|---:|---|
| **`tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`** | `5,542,598` Б | **Прямая прошивка через браузер из родного меню Tenda** (`192.168.0.1` -> Обновление ПО, без ошибки `"Format error!"`). |
| **`tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin`** | `5,542,534` Б | **Прошивка в 1 клик по TFTP и раскирпичивание** через загрузчик (`192.168.1.6:69`, безопасный односегментный `cs6c`). |
| **`tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin`** | `5,542,534` Б | Обновление поверх уже установленной OpenWrt (через LuCI или `sysupgrade`). |
| **`Tenda_AC10_V1_Offline_Autonomous_Toolkit.zip`** | `72,336` Б | Все `.bat` / `.ps1` / `.py` скрипты автопрошивки, переноса настроек провайдера из `RouterCfm.cfg` и восстановления сети ПК. |
| **`Tenda_AC10_V1_Build_and_Router_Scripts.zip`** | `39,247` Б | Сборочный скрипт `build_hybrid_openwrt_ac10.sh`, `set-mib.sh`, `dir842-l2flush`, `tenda-ac10-v1.dts`, конфиг ядра и утилита `mtd1`. |
| **`Tenda_AC10_V1_Stock_TFTP_Recovery.bin`** | `7,588,884` Б | Чистая заводская прошивка Tenda `V15.03.06.23` для отката обратно на сток по TFTP. |

## Контрольные суммы | SHA-256 Checksums (`v4.14.187-r3-ac10-hybrid`)

```text
7bd99d144fb90fade7f7ecace0d2ebc2de7e34afb627231cc9305bd3ccceabc7  tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
7bd99d144fb90fade7f7ecace0d2ebc2de7e34afb627231cc9305bd3ccceabc7  tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin
8f77ff1b8eaf4b0cbc06db8c377ed3a22235ae1db45f65f0fef592f627e5af22  tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin
f5c7d1755689dd5319420289d8ebd4e661d418f56d99b775f6111c48a3c96345  tenda-ac10-v1.dtb
a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa  Tenda_AC10_V1_Stock_TFTP_Recovery.bin
d3240d5adbf7f0b498cac3c33cc463a4f214ccfc57948f439fdc0b282ba10b42  Tenda_AC10_V1_Offline_Autonomous_Toolkit.zip
171574fa8c9f4960b03cc0191cb6660f677cff9d93faca44fb819cfbcdbbeda2  Tenda_AC10_V1_Build_and_Router_Scripts.zip
```
