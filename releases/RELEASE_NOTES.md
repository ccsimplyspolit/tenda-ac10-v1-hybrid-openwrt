# Release v4.14.187-ac10-hybrid: Tenda AC10 V1.0 Hybrid OpenWrt 4.14 Production Build

**Target Device**: Tenda AC10 V1.0 (Realtek RTL8197FS-VE5 + RTL8822BE + RTL8367RB-VB)  
**Linux Kernel**: 4.14.187 (MIPS 24KEc, mipsel)  
**OpenWrt Userland**: OpenWrt 19.07 with LuCI Web Interface  

## Key Features & Verified Fixes
1. **Wire-Speed Hardware NAT**: Realtek ASIC SRAM Table Lookup Unit (TLU) offload delivers full line-rate ~895–940 Mbps routing with 0.0% CPU overhead (all 9 MIPS32 switch/VLAN/ASIC port-map patches verified for Tenda AC10 V1.0: `WAN = Port 3`, `LAN1..3 = Ports 2..0`).
2. **Dual-Band Wireless**:
   - **5 GHz 802.11a/n/ac Wave 2 (up to 866.7 Mbps VHT80)** via PCIe `RTL8822BE` (`mac80211 / hostapd`) with Skyworth `SE5003L1` external PA/LNA (`RFE Type 6` ELF relocation patch + dynamic `HW_WLAN0_11N_XCAP` & `HW_WLAN0_WLAN_ADDR` injection from `/dev/mtd1`).
   - **2.4 GHz 802.11b/g/n (up to 300 Mbps)** via integrated `RTL8197FS` (`rtl8192cd`) with Skyworth `SKY85303-11` (`RFE Type 5`) + dynamic `/dev/mtd1` RF calibration + `manual_edca=1` & `disable_txsc=1` uTP/BitTorrent stability fixes.
3. **1-Click Autonomous ISP & Wi-Fi Settings Migration (`Configure_OpenWrt_ISP_WAN_and_WiFi.bat`)**:
   - Automatically extracts and provisions your ISP cloned `WAN MAC`, `DHCP MTU`, custom upstream `DNS`, `LAN DHCP` pool & `Static DHCP` reservations, and 2.4G/5G Wi-Fi SSIDs, channels & `WPA2-PSK` passphrases from your stock `RouterCfm.cfg` backup over local SSH with zero internet required.
4. **First-Boot JFFS2 Overlay Auto-Formatting**: `/lib/preinit/80_mount_root` detects stale stock Tenda bytes on `rootfs_data` and formats a clean ~2.41 MB writable `JFFS2` overlay automatically.
5. **CVE-2026-11405 & Stock Backdoor Immunity**: Stock vendor cloud telemetry (`ucloud_v2`, `sntp`) and unauthenticated debug endpoints (`/cgi-bin/DownloadFlash`, `/goform/telnet`) are completely eliminated.

## Verification Checksums (SHA-256)
```text
33b5948f0acdcb76178d759f2414adc9a5b5be148de32cc1b814718526142d41  tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
33b5948f0acdcb76178d759f2414adc9a5b5be148de32cc1b814718526142d41  tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin
9c1619ff37453d0383d8754a314b2ced91ec7662956d3de33b208b7b12070baa  tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin
f5c7d1755689dd5319420289d8ebd4e661d418f56d99b775f6111c48a3c96345  tenda-ac10-v1.dtb
a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa  Tenda_AC10_V1_Stock_TFTP_Recovery.bin
1c15ebf56d78f5782d658c7d75d3599489908ec2950753fc0a6c345e54d65f64  Tenda_AC10_V1_Offline_Autonomous_Toolkit.zip
```

## Quick Installation & Autonomous Migration (Zero Internet Required)
1. **Step 1 — Flash Hybrid OpenWrt 4.14.187**:
   - **Via TFTP (Recommended)**: Plug Ethernet into `LAN1`, `LAN2`, or `LAN3` (NOT `WAN`) and run `offline_autonomous_tools/Flash_Hybrid_OpenWrt_4.14_TFTP.bat` while holding `RST` for 8–15s on power-up.
   - **Via Stock Web UI**: Upload `tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin` at `http://192.168.0.1` (*System Settings -> Firmware Upgrade*).
2. **Step 2 — 1-Click ISP WAN, DNS, DHCP & Wi-Fi Migration**:
   - Once OpenWrt boots at `http://192.168.0.1` (~90s), run `offline_autonomous_tools/Configure_OpenWrt_ISP_WAN_and_WiFi.bat`.
3. **Emergency Solderless Rollback to Stock+**:
   - Run `offline_autonomous_tools/Offline_TFTP_Recovery_and_Flash.bat` followed by `offline_autonomous_tools/Restore_Optimized_Config_and_WAN.bat`.
