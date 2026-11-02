# Сборка Hybrid OpenWrt 4.14.187 с нуля / Reproducible Build Guide (RU / EN)

Весь процесс сборки прошивки `v4.14.187-r3-ac10-hybrid` автоматизирован в одном самодостаточном скрипте [**`build_hybrid_openwrt_ac10.sh`**](../../build_hybrid_openwrt_ac10.sh) и проверяется в облаке через GitHub Actions ([**`.github/workflows/build-ac10-hybrid-openwrt.yml`**](../../.github/workflows/build-ac10-hybrid-openwrt.yml)). Вам не нужно вручную собирать старый тулчейн на двое суток или править бинарники в hex-редакторе руками.

---

## 1. Сборка одной командой на Ubuntu 22.04 / WSL2 (RU / EN)

```bash
sudo apt-get update
sudo apt-get install -y python3 squashfs-tools xz-utils device-tree-compiler \
    binutils wget curl ca-certificates git

git clone https://github.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt.git
cd tenda-ac10-v1-hybrid-openwrt
chmod +x build_hybrid_openwrt_ac10.sh
./build_hybrid_openwrt_ac10.sh
```

Через 1–2 минуты в папке `02_Compiled_Hybrid_OpenWrt_4.14_Firmware/` появятся четыре проверенных файла:
- `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin` (`5,681,798` байт, монолитный `cs6c` с записью по `0x00030000` для TFTP);
- `tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin` (`5,681,798` байт, для обновления через LuCI / `sysupgrade`);
- `tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin` (`5,681,862` байт, обёрнутый в 64-байтный заголовок `trx2` с кодом модели `0x00030028` для прошивки прямо из родного меню Tenda без ошибки `"Format error!"`);
- `tenda-ac10-v1.dtb` (`4,182` байта, скомпилированное дерево устройств).

---

## 2. Что именно делает `build_hybrid_openwrt_ac10.sh` внутри (по шагам)

Если вы хотите понять устройство сборки или адаптировать её под родственную плату на `RTL8197FS`, вот вся цепочка без магии:

1. **Компиляция `tenda-ac10-v1.dtb` (`config/tenda-ac10-v1.dts`):**  
   Прописывает 64 МБ RAM, разметку флешки на 8 МБ (`bootloader` 128 КБ, `calibration` 64 КБ, `firmware` 7872 КБ, `cfm` 128 КБ), шину свитча SMI (`GPIO 18/19`), правильный пин аппаратного сброса `RTL8367RB` (`<&gpio1 26 GPIO_ACTIVE_LOW>` = `GPIO 58`) и кнопки/светодиоды корпуса.
2. **Патчинг ядра `vmlinux` и сетевого стека (34 точечных MIPS32 LE патча):**  
   У донорского D-Link DIR-842 R1 порт WAN сидит на чётном `Port 4`, а у Tenda AC10 V1.0 — на **нечётном `Port 3`** (`mask 0x08`, а `LAN 1–3` — это `Ports 2, 1, 0`, `mask 0x07`). Скрипт накладывает 34 точечных MIPS32 LE патча:
   - сдвиг `sll $a1, $a1, 16` для записи PVID нечётного Port 3 WAN в старшие 16 бит регистра;
   - активация `SWTCR0 |= 0x400C` (`WANRouteMode=ToCpu`) в шлюзе `gw_prog` для одновременной работы аппаратного NAT `hwnat=1` (~940 Мбит/с при 0.5% CPU) и Wi-Fi без черных дыр;
   - асимметричный контроль потока RGMII `trunk_pause=3` (`PCRP0[17:16]=1`, `EXT1 0x1311 |= 0x0020 FORCE_RXPAUSE`) между RTL8367RB и RTL8197F;
   - увеличение порогов буферов `SBFCR1` (`FCOFF=320, FCON=380`);
   - мягкий сторожевой таймер Stage 1 (<2 мс FIFO drain) в `rtl819x_hang_check` от клина свитча при пиковых нагрузках;
   - смещение секций `.data/.bss/_stack` загрузчика `lzma-loader` на `+0x4000`, чтобы увеличенное LZMA-ядро не перетёрло собственные таблицы распаковки.
3. **Включение усилителей 5 ГГц `Skyworth SE5003L1` (`RFE Type 6`) и стабильного `VHT80` (80 МГц):**  
   - Дописывает в `.rodata` и `.rel.rodata` модуля `rtw88_8822b.ko` структуру `rfe_info[6]` с инициализацией `rtw8822b_config_rfe_efem` и регистрами базовой полосы `0x82C/0x830/0x838/0x83C`;
   - Увеличивает таймаут опроса RF-регистра 0x33 со 100 до 1000 циклов (2 мс) на смещениях `.text+0x2EDC` и `.text+0x2F7C` для предотвращения отвалов 80 МГц на ревизии чипа B-cut;
   - Активирует порог CCA в регистре `REG_L1WT` (`0x9194b2b9`);
   - Фиксирует скорость передачи служебных и EAPOL-кадров на `DESC_RATE6M` (`0x04`) в `rtw88_core.ko` на `.text+0x2CC0`.
4. **Вшивание эксплуатационных фиксов и калибровок в SquashFS RootFS:**
   - `/lib/preinit/80_mount_root` — автоочистка остатков стокового SquashFS в `mtd5` перед созданием `JFFS2` (настройки сохраняются с первого ребута);
   - `/lib/preinit/00_preinit.conf` — `pi_preinit_no_failsafe="y"` (защита от ложного Failsafe на плавающем `GPIO 6`);
   - `/bin/set-mib.sh` + `/etc/rc.d/S18ac10-hwparams` — чтение базового MAC и емкости кварца `XCAP`, а также динамическая подгрузка всех заводских таблиц калибровки усилителей `Skyworks SKY85303-11` PA/LNA (CCK, HT40, ther, xcap, regdomain, trswitch) из `/dev/mtd1` с включением аппаратной агрегации `ampdu=1` + `amsdu=1` и отключением сбойного `disable_txsc=1`;
   - `/etc/init.d/dir842-asic` (`wait_netif_mac` ожидает готовности `eth0.2` и клонированного `eth0.1`) + сброс `dir842-l2flush` + одновременная работа аппаратного NAT `hwnat=1` и программного Flow Offloading;
   - `/etc/uci-defaults/99-ac10-defaults` — `LAN 192.168.0.1`, 5 ГГц `VHT80` (80 МГц) ch36 `23 dBm` (PHY до 866.7 Мбит/с), чистый IPv4 + DHCP Option 6 (`1.1.1.1,8.8.8.8,192.168.0.1`) для Apple iOS Encrypted DNS, изоляция `uhttpd` и `dnsmasq` от WAN, буфер логов 256 КБ и `nf_conntrack_max=16384`.
5. **Безопасная упаковка контейнеров (`cs6c` и `trx2`):**  
   Собирает единый односегментный образ `cs6c` (`burn_addr = 0x00030000`, 16-битная BE контрольная сумма до `0x0000`), который гарантированно обходит баг самоуничтожения загрузчика `$s7=0` на `0x80001C2C`, а для `webupgrade.bin` добавляет сверху 64-байтный заголовок U-Boot `trx2` (`ih_magic=0x27051956`, `ih_os=2`, `ih_ver=0x00030028`).

---

## 3. Облачная сборка без Linux под рукой (GitHub Actions)

Если у вас только Windows без WSL, сделайте Fork репозитория, откройте вкладку **Actions -> Build Tenda AC10 V1.0 Hybrid OpenWrt 4.14 -> Run workflow** — облачный раннер соберёт образы с нуля, сверит заголовки и выложит готовый архив в Artifacts.
