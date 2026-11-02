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
2. **Патчинг ядра `vmlinux` под распиновку портов Tenda AC10 V1.0:**  
   У донорского D-Link DIR-842 R1 порт WAN сидит на чётном `Port 4`, а у Tenda AC10 V1.0 — на **нечётном `Port 3`** (`mask 0x08`, а `LAN 1–3` — это `Ports 2, 1, 0`, `mask 0x07`). Скрипт накладывает 9 точечных MIPS32 LE патчей на `vmlinux` (включая сдвиг `sll $a1, $a1, 16` для записи PVID нечётного порта в старшие 16 бит регистра) и двигает секции `.data/.bss/_stack` загрузчика `lzma-loader` на `+0x4000`, чтобы увеличенное LZMA-ядро не перетёрло собственные таблицы распаковки.
3. **Включение внешних усилителей 5 ГГц `Skyworth SE5003L1` (`RFE Type 6`) в `rtw88_8822b.ko`:**  
   Дописывает в `.rodata` и `.rel.rodata` модуля `rtw88_8822b.ko` структуру `rfe_info[6]` с инициализацией `rtw8822b_config_rfe_efem` и регистрами базовой полосы `0x82C/0x830/0x838/0x83C`. Без этого патча из-за пустого заводского OTP eFuse (`0xFF`) чип падает на внутренний `RFE 0` и теряет 17 дБ мощности.
4. **Вшивание всех 14 эксплуатационных фиксов в SquashFS RootFS:**
   - `/lib/preinit/80_mount_root` — автоочистка остатков стокового SquashFS в `mtd5` перед созданием `JFFS2` (чтобы настройки сохранялись с первого же ребута);
   - `/lib/preinit/00_preinit.conf` — `pi_preinit_no_failsafe="y"` (защита от ложного Failsafe на висящем в воздухе `GPIO 6`);
   - `/bin/set-mib.sh` + `/etc/rc.d/S18ac10-hwparams` — чтение заводского `HW_NIC0_ADDR` и калибровки кварца `HW_WLAN0_11N_XCAP` из `/dev/mtd1`;
   - `/etc/init.d/dir842-asic` (`wait_netif_mac` ждёт и `eth0.2`, и клонированный `eth0.1` перед вызовом `gw_prog`) + `/etc/rc.d/S99asic-wifi-settle` + `hwnat=0` и `flow_offloading='1'` по умолчанию;
   - `/etc/uci-defaults/99-ac10-defaults` — `LAN 192.168.0.1`, 5 ГГц `VHT20` ch36 `23 dBm` (`ifname='wlan1'`), чистый IPv4 + DHCP Option 6 (`1.1.1.1,8.8.8.8,192.168.0.1`) для Apple iOS Encrypted DNS, изоляция `uhttpd` и `dnsmasq` от WAN, буфер логов 256 КБ и `nf_conntrack_max=16384`.
5. **Безопасная упаковка контейнеров (`cs6c` и `trx2`):**  
   Собирает единый односегментный образ `cs6c` (`burn_addr = 0x00030000`, 16-битная BE контрольная сумма до `0x0000`), который гарантированно обходит баг самоуничтожения загрузчика `$s7=0` на `0x80001C2C`, а для `webupgrade.bin` добавляет сверху 64-байтный заголовок U-Boot `trx2` (`ih_magic=0x27051956`, `ih_os=2`, `ih_ver=0x00030028`).

---

## 3. Облачная сборка без Linux под рукой (GitHub Actions)

Если у вас только Windows без WSL, сделайте Fork репозитория, откройте вкладку **Actions -> Build Tenda AC10 V1.0 Hybrid OpenWrt 4.14 -> Run workflow** — облачный раннер соберёт образы с нуля, сверит заголовки и выложит готовый архив в Artifacts.
