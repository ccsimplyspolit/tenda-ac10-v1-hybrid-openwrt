# Release v4.14.187-r2-ac10-hybrid: Tenda AC10 V1.0 Hybrid OpenWrt 4.14 Hardened Production Build (RU / EN)

**Target Device / Устройство**: Tenda AC10 **V1.0 ONLY** (`Realtek RTL8197FS-VE5` + `RTL8822BE` + `RTL8367RB-VB`, 8 MB SPI NOR, 64 MB DDR2 SiP) — **NEVER flash on V2.0 / V3.0 (eCos, 2 MB)!**  
**Linux Kernel**: `4.14.187` (`MIPS 24KEc`, `mipsel`) | **OpenWrt Userland**: `OpenWrt 19.07` + `LuCI` (`http://192.168.0.1`)  
**Documentation Portal**: https://ccsimplyspolit.github.io/tenda-ac10-v1-hybrid-openwrt/  
**Bilingual Wiki**: https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/wiki  
**Official 4PDA Guide (#3585)**: https://4pda.to/forum/index.php?showtopic=885989&view=findpost&p=145799909  

---

## Что нового и все исправленные проблемы (RU) | Hardened Fixes Baked Out-of-the-Box (EN)

В сборке **r2 (`v4.14.187-r2-ac10-hybrid`)** непосредственно внутрь образов прошивки (`factory.bin`, `sysupgrade.bin`, `webupgrade.bin`) и автономного мигратора (`Configure_OpenWrt_ISP_WAN_and_WiFi.bat`) вшиты **все 14 инженерных исправлений**, выявленных и проверенных на живом роутере под реальной нагрузкой:

1. **5 ГГц Wi-Fi (`RTL8822BE` + `Skyworth SE5003L1` RFE Type 6) с нулём отвалов**:
   - Бинарный ELF-патч релокаций `rtw88_8822b.ko` под внешние усилители `RFE Type 6` (устранено затухание `-17 dB` на пустом заводском OTP eFuse `0xFF`).
   - Автоматическая инъекция заводской подстройки кварца `HW_WLAN0_11N_XCAP` и MAC из `/dev/mtd1` (`/bin/set-mib.sh`), жёсткая привязка по PCIe-пути (`ifname='wlan1'`) и эталонный профиль **`VHT20`, канал `36`, `country='US'` (`23 dBm` / `200 мВт`)** — 0 обрывов и 0 повторных передач.
2. **Одновременная работа кабеля и Wi-Fi без «чёрной дыры» (`hwnat=0` + Software Flow Offloading)**:
   - По умолчанию `hwnat=0` + `firewall.flow_offloading='1'` при активном аппаратном режиме коммутатора `dir842.asic.role='router'` и сторожевом механизме `fabric_autoreset=3` (`fabric_gw_rearm=1`): полная скорость **~350–500 Мбит/с** одновременно по проводу и Wi-Fi «из коробки» (при необходимости чисто кабельного 1 Гбит/с — включение `hwnat=1` одной командой даёт **~940 Мбит/с** при 0.5% CPU).
3. **Синхронизация клонированного WAN MAC при холодном старте (`wait_netif_mac`)**:
   - Исключена гонка при загрузке на провайдерах с привязкой по MAC: `/etc/init.d/dir842-asic` теперь ожидает применения как `eth0.2` (LAN MAC), так и клонированного `eth0.1` (`network.wan.macaddr`) перед программированием таблиц `gw_prog`, а `S99asic-wifi-settle` перепрограммирует L2 после подъёма радиомодулей.
4. **Полная совместимость с Apple iOS / macOS (RFC 9462 DDR Encrypted DNS & IPv6 Clean-Up)**:
   - Удалён немаршрутизируемый `ula_prefix`, отключены `ra`/`dhcpv6`, выставлен `dhcp_option '6,1.1.1.1,8.8.8.8,192.168.0.1'` — устройства Apple мгновенно переходят на защищённый HTTP/3 QUIC DoH (`1.1.1.1:443`) без предупреждений «Эта сеть блокирует защищенный трафик DNS».
5. **Сокетная изоляция от внешней подсети провайдера (`/24` Shared VLAN)**:
   - `dnsmasq` изолирован правилом `notinterface='eth0.1'`, а `uhttpd` привязан строго к `192.168.0.1:80` и `127.0.0.1:80` (`redirect_https='0'`), кольцевой буфер логов увеличен до `256 КБ`.
6. **Безопасная прошивка в 1 клик из заводского меню Tenda (`webupgrade.bin`) и по TFTP (`factory.bin`)**:
   - Односегментный `cs6c` (`0x00030000`) защищает от бага затирания загрузчика (`0x80001C2C`, `$s7=0`), `80_mount_root` автоматически форматирует чистый `JFFS2` поверх стокового мусора в `mtd5`, а `pi_preinit_no_failsafe="y"` защищает от ложного Failsafe на висящем `GPIO 6`.

Полный технический разбор всех проблем и решений:
- **RU**: [`docs/openwrt_hybrid/ENGINEERING_POSTMORTEM_ALL_PROBLEMS_AND_SOLUTIONS_RU.md`](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/blob/main/docs/openwrt_hybrid/ENGINEERING_POSTMORTEM_ALL_PROBLEMS_AND_SOLUTIONS_RU.md)
- **EN**: [`docs/openwrt_hybrid/ENGINEERING_POSTMORTEM_ALL_PROBLEMS_AND_SOLUTIONS_EN.md`](https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/blob/main/docs/openwrt_hybrid/ENGINEERING_POSTMORTEM_ALL_PROBLEMS_AND_SOLUTIONS_EN.md)

---

## Verification Checksums / Контрольные суммы (SHA-256)
```text
5954e788b577597c5fe1bd23e18158fb5e368226bf3bc69fca7e0b18cd77ad76  tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
5954e788b577597c5fe1bd23e18158fb5e368226bf3bc69fca7e0b18cd77ad76  tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin
87da99ea1df7312b41e26e3f9fa449a7863427e7b84a50790a0727694583e056  tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin
f5c7d1755689dd5319420289d8ebd4e661d418f56d99b775f6111c48a3c96345  tenda-ac10-v1.dtb
a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa  Tenda_AC10_V1_Stock_TFTP_Recovery.bin
edeb3fb6d6834da5baf8aa9e05379f8e9c47f980b090e3d6e4d6bef251527e81  Tenda_AC10_V1_Offline_Autonomous_Toolkit.zip
```
