# Tenda AC10 V1.0 — 100% Autonomous Offline Recovery & Verification Suite

All tools in this folder run **100% offline** with **zero external dependencies** (no internet required, no `pip` packages, no Windows optional `tftp.exe` feature required) and enforce a strict `try / finally` network failsafe that **always restores your PC's physical Ethernet adapter (`Intel I225-V`) back to automatic DHCP & DNS**, even if the router takes 20–30 minutes to recover or a script is interrupted with `Ctrl+C`.

---

## Quick One-Click Launchers (`.bat`)

| Launcher | Purpose | Default Target |
|---|---|---|
| **`Offline_TFTP_Recovery_and_Flash.bat`** | Flashes stock recovery (`backups\Tenda_AC10_V1_Stock_TFTP_Recovery.bin`, `7,588,884` B) or a custom OpenWrt `cs6c` image to the Realtek Booter at `192.168.1.6:69`. Pre-validates headers, checksums (`0x0000`), and blocks lethal 2-segment `cs6c+hsqs` images before touching the network. | `192.168.1.6:69` (Connect cable to **LAN1 / LAN2 / LAN3**, never WAN) |
| **`Restore_Optimized_Config_and_WAN.bat`** | Restores `backups\RouterCfm_optimized_v1.cfg` (`25,369` B) to `192.168.0.1`, recovering the ISP-bound WAN MAC (`<YOUR_WAN_MAC>`), disabling phantom `br2`/`vlan3` (`iptv.stb.enable=0`), disabling `ucloud_v2`, setting `sys.maxconn=8192`, and setting `sys.timentpserver=time.google.com`. | `http://192.168.0.1` |
| **`Emergency_Restore_PC_Network_DHCP.bat`** | Instant 3-second emergency failsafe that removes any static IP (`192.168.1.116` / `192.168.0.116`) and restores automatic DHCP and DNS on `Ethernet` (`Intel I225-V`). | Local PC Adapter (`Ethernet`) |
| **`Verify_All_Dumps_Chips_and_Backups.bat`** | Runs 81 cryptographic and structural checks across all flash dumps, bootloader/kernel headers, RF calibration (`xcap=27/46`, `RFE=6`), `vmlinux_stock.bin` `mib_table` keys, NVRAM configs, and backup archives. | Offline local files |

---

## Verified Hardware & Bootloader Facts (Reverse-Engineered from `booter_stage2_v3.4.11B.9_0x80000000.bin`)

1. **Bootloader Drops ICMP Ping (`0x80001010..0x80001018`)**:
   - Realtek Booter v3.4.11B.9 checks `ip_hdr[9] == 0x11` (UDP) and drops all ICMP packets. `ping 192.168.1.6` will **never** reply in bootloader mode. `Offline_TFTP_Recovery_and_Flash.ps1` probes `192.168.1.6:69` directly using RFC 1350 UDP TFTP `WRQ` packets.
2. **Switch Port 3 (WAN) Powered Down in Bootloader (`0x8000ec6c..0x8000ed58`)**:
   - `lan_wan_isolation` sets LAN mask `0xF7` and writes `0x0936` to PHY register `0x1B03` to power down Switch Port 3 (WAN). Always connect your Ethernet cable to **LAN1, LAN2, or LAN3** (Switch Ports 2, 1, or 0).
3. **`AutoBurn` (`0x800019d0`) & `check_image` (`0x8000dd10`)**:
   - Factory Stock TFTP image (`Tenda_AC10_V1_Stock_TFTP_Recovery.bin`, `7,588,884` B, SHA-256 `a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa`) uses 2-segment `cr6c` (`2,145,298` B) + `hsqs` (`5,443,586` B), both with 16-bit BE additive checksum `0x0000`.
   - Custom OpenWrt `cs6c` images **must be single-segment** (`file_size == 16 + seg_len`) because a 2-segment `cs6c` + `hsqs` image triggers a bootloader bug at `0x80001c2c` (`move $s7, $s2` with `$s2=0`) that erases flash offset `0x00000000`.
