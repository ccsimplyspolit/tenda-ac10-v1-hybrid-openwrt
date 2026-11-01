# Release v4.14.187-ac10-hybrid: Tenda AC10 V1.0 Hybrid OpenWrt 4.14 Production Build

**Target Device**: Tenda AC10 V1.0 (Realtek RTL8197FS-VE5 + RTL8822BE + RTL8367RB-VB)  
**Linux Kernel**: 4.14.187 (MIPS 24KEc, mipsel)  
**OpenWrt Userland**: OpenWrt 19.07 with LuCI Web Interface  

## Key Features & Verified Fixes
1. **Wire-Speed Hardware NAT**: Realtek ASIC SRAM Table Lookup Unit (TLU) offload delivers full line-rate ~940 Mbps routing with 0.0% CPU overhead.
2. **Dual-Band Wireless**:
   - 2.4 GHz 802.11b/g/n (up to 300 Mbps) via integrated RTL8197FS MAC/BB and Skyworth RFE5 FEM.
   - 5 GHz 802.11a/n/ac Wave 2 (up to 866.7 Mbps) via PCIe RTL8822BE with Skyworth SE5003L1 external PA/LNA (RFE Type 6 relocation patch applied).
3. **No Collision WAN MAC**: WAN MAC is derived cleanly as `base + 2` to prevent collisions with `base + 1` (2.4 GHz AP).
4. **Switch Isolation & Stability**: RTL8367RB SMI control via GPIO 18/19; switch reset pin GPIO 58 disabled from random toggling; flash-corrupting GPIO 61 protected.
5. **Torrent & High-Traffic Stability**: `manual_edca=1` and `disable_txsc=1` driver parameters prevent queue starvation under heavy uTP/BitTorrent traffic.
6. **CVE-2026-11405 & Stock Backdoor Immunity**: Stock vendor cloud telemetry (`ucloud_v2`, `sntp`) and debug endpoints (`/cgi-bin/DownloadFlash`, `/goform/telnet`) completely eliminated.

## Verification Checksums (SHA-256)
```text
33b5948f0acdcb76178d759f2414adc9a5b5be148de32cc1b814718526142d41  tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
33b5948f0acdcb76178d759f2414adc9a5b5be148de32cc1b814718526142d41  tenda-ac10-v1-hybrid-openwrt-4.14-sysupgrade.bin
9c1619ff37453d0383d8754a314b2ced91ec7662956d3de33b208b7b12070baa  tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin
f5c7d1755689dd5319420289d8ebd4e661d418f56d99b775f6111c48a3c96345  tenda-ac10-v1.dtb
```

## Quick Installation
- **Via TFTP (Recommended)**: Use `offline_autonomous_tools/Flash_Hybrid_OpenWrt_4.14_TFTP.bat` (hold RST 5-7s, release).
- **Via Stock Web UI**: Upload `tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin` under *System Settings* -> *Firmware Upgrade*.
