# Hybrid OpenWrt 4.14.187 Port: Architecture, Screenshots & 1-Click Setup (EN)

> **Navigation:** [Home (EN)](EN-Home) | [Русская версия](RU-Hybrid-OpenWrt-4.14-Port) | [Wiki Portal](Home)

**Hybrid OpenWrt 4.14.187 (`v4.14.187-r3-ac10-hybrid`)** pairs **OpenWrt 19.07 userland + LuCI** (`http://192.168.0.1`, Dropbear SSH, `fw3`, persistent `JFFS2` overlay) with a patched **Linux 4.14.187** kernel tailored to the Tenda AC10 V1.0's `RTL8197FS` SoC, `RTL8367RB` switch, and `RTL8822BE` 5 GHz PCIe radio.

---

## 1. Live LuCI Web Panel Screenshots

| System Overview (`Status -> Overview`) | 5 GHz `23 dBm` Wireless (`Network -> Wireless`) |
|---|---|
| ![Overview](https://raw.githubusercontent.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/main/docs/images/01_luci_status_overview.png) | ![Wireless](https://raw.githubusercontent.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/main/docs/images/02_luci_wireless_5ghz.png) |

| `RTL8367RB` VLAN Switch (`Network -> Switch`) | Software Flow Offloading (`Network -> Firewall`) |
|---|---|
| ![Switch](https://raw.githubusercontent.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/main/docs/images/04_luci_switch_vlans.png) | ![Firewall](https://raw.githubusercontent.com/ccsimplyspolit/tenda-ac10-v1-hybrid-openwrt/main/docs/images/05_luci_firewall_offload.png) |

---

## 2. Key Fixes and Architectural Improvements in `r3` (`v4.14.187-r3-ac10-hybrid`)

1. **Full-Power 5 GHz `RTL8822BE` with Rock-Solid `VHT80` (80 MHz):**
   - Tenda left the `RTL8822BE` OTP eFuse blank (`0xFF`). We binary-patched `rtw88_8822b.ko` ELF relocations to add `rfe_info[6]` (`rtw8822b_config_rfe_efem`, BB regs `0x82C/0x830/0x838/0x83C`), and `/bin/set-mib.sh` injects each unit's factory `HW_WLAN0_11N_XCAP` and MAC from `/dev/mtd1` on boot.
   - In `r3`, RF register 0x33 polling timeout was increased 10x from 100 to 1000 iterations (2 ms) at `.text+0x2EDC` and `.text+0x2F7C`, CCA threshold register `REG_L1WT` (`0x9194b2b9`) was enabled, and management/EAPOL frames were fixed to `DESC_RATE6M` (`0x04`) in `rtw88_core.ko`.
   - Default profile is locked to **`VHT80` (80 MHz), Channel `36`, `23 dBm` (200 mW)** delivering up to 866.7 Mbps PHY with zero link drops under continuous heavy load.
2. **Simultaneous Hardware NAT (940 Mbps) & Wi-Fi Routing (`SWTCR0 |= 0x400C` / `WANRouteMode=ToCpu`):**
   - In `r3`, bit `WANRouteMode=ToCpu` was patched in `gw_prog` inside `vmlinux` paired with `dir842-l2flush`. Hardware NAT offloading (`hwnat=1`) delivers ~940 Mbps wired line-rate at 0.5% CPU, while simultaneously routing all Wi-Fi traffic at full speed without blackholes.
3. **2.4 GHz Skyworks `SKY85303-11` PA/LNA Factory Calibration from `mtd1`:**
   - `/bin/set-mib.sh` dynamically extracts factory calibration tables from `/dev/mtd1` on boot (`pwrlevelCCK_A/B`, `pwrlevelHT40_1S_A/B`, `ther`, `xcap`, `regdomain`, `trswitch`), enables hardware aggregation `ampdu=1` + `amsdu=1`, and disables `disable_txsc=1`. 2.4 GHz delivers full factory power and penetration.
4. **Asymmetric Flow Control & Two-Stage Watchdog:**
   - Enables RGMII asymmetric flow control `trunk_pause=3` (`PCRP0[17:16]=1`, `EXT1 0x1311 |= 0x0020 FORCE_RXPAUSE`), buffer thresholds in `SBFCR1` (`FCOFF=320, FCON=380`), and non-disruptive Stage 1 soft FIFO queue drain (<2 ms) in `rtl819x_hang_check`.
5. **Cold-Boot Cloned WAN MAC Sync (`wait_netif_mac`):**
   - `/etc/init.d/dir842-asic` waits for both `eth0.2` (LAN) and cloned `eth0.1` (`network.wan.macaddr`) before programming `gw_prog`.
6. **Odd WAN Port 3 & `GPIO 58` Switch Reset:**
   - `tenda-ac10-v1.dts` binds switch reset `<&gpio1 26 GPIO_ACTIVE_LOW>` (`GPIO 58`), paired with MIPS32 LE `vmlinux` patches fixing odd `Port 3` WAN PVID upper-halfword shift and L2 masks.
7. **Apple iOS Encrypted DNS (RFC 9462 DDR) & WAN Socket Lockdown:**
   - Removed unrouted `ula_prefix` and set `dhcp_option '6,1.1.1.1,8.8.8.8,192.168.0.1'` for instant HTTP/3 QUIC DoH without iOS warnings; `uhttpd` and `dnsmasq` are isolated from `eth0.1`.

---

## 3. Flashing & 1-Click Offline ISP Migration

1. Save a backup of your stock Tenda `RouterCfm.cfg` before flashing if your ISP locks to a cloned WAN MAC.
2. Flash **`tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin`** directly from the stock Tenda Web UI (`192.168.0.1`), OR run **`offline_autonomous_tools\Flash_Hybrid_OpenWrt_4.14_TFTP.bat`** as Administrator with Ethernet plugged into **LAN 1–3** while holding `RST/WPS` at power-on for 7–10 seconds.
3. Wait **90–120 seconds** on first boot while `80_mount_root` formats a clean `JFFS2` overlay on `mtd5`.
4. Plug your ISP cable into blue **WAN** and run **`offline_autonomous_tools\Configure_OpenWrt_ISP_WAN_and_WiFi.bat`** to migrate cloned WAN MAC, WAN IP/DNS, static DHCP leases, and Wi-Fi SSIDs/passwords over local SSH in 10 seconds.
