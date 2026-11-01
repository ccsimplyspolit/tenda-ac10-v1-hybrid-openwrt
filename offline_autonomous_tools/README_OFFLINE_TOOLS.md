# Tenda AC10 V1.0 — 100% Autonomous Offline Recovery & Verification Suite

All tools in this folder run **100% offline** with **zero external dependencies** (no internet required, no `pip` packages, no Windows optional `tftp.exe` feature required) and enforce a strict `try / finally` network failsafe that **always restores your PC's physical Ethernet adapter (physical Ethernet NIC) back to automatic DHCP & DNS**, even if the router takes 20–30 minutes to recover or a script is interrupted with `Ctrl+C`.

---

## Quick One-Click Launchers (`.bat`)

| Launcher | Purpose | Default Target |
|---|---|---|
| **`Offline_TFTP_Recovery_and_Flash.bat`** | Flashes stock recovery (`backups\Tenda_AC10_V1_Stock_TFTP_Recovery.bin`, `7,588,884` B) or a custom OpenWrt `cs6c` image to the Realtek Booter at `192.168.1.6:69`. Pre-validates headers, checksums (`0x0000`), and blocks lethal 2-segment `cs6c+hsqs` images before touching the network. | `192.168.1.6:69` (Connect cable to **LAN1 / LAN2 / LAN3**, never WAN) |
| **`Flash_Hybrid_OpenWrt_4.14_TFTP.bat`** | 1-Click autonomous TFTP flasher for Hybrid OpenWrt 4.14 (`tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin`). Auto-elevates UAC, auto-detects firmware across multiple fallback directories, manages temporary firewall rules, and restores DHCP/DNS in `finally`. | `192.168.1.6:69` (LAN1/LAN2/LAN3) |
| **`Configure_OpenWrt_ISP_WAN_and_WiFi.bat`** | Autonomous post-flash OpenWrt 4.14 ISP WAN MAC & Wi-Fi configurator. Dynamically parses cloned WAN MAC and Wi-Fi credentials from `backups\RouterCfm_optimized_v1.cfg`, connects to OpenWrt at `192.168.0.1` via SSH, configures `network.wan.macaddr`, `network.wan_eth0_1_dev.macaddr`, Wi-Fi SSIDs/WPA2-PSK, reloads services, and verifies WAN status. | `192.168.0.1` (OpenWrt `root@192.168.0.1` over LAN) |
| **`Restore_Optimized_Config_and_WAN.bat`** | Restores `backups\RouterCfm_optimized_v1.cfg` (`25,369` B) to `192.168.0.1`, recovering the ISP-bound WAN MAC (`<YOUR_WAN_MAC>`), disabling phantom `br2`/`vlan3` (`iptv.stb.enable=0`), disabling `ucloud_v2`, setting `sys.maxconn=8192`, and setting `sys.timentpserver=time.google.com`. | `http://192.168.0.1` |
| **`Emergency_Restore_PC_Network_DHCP.bat`** | Instant 3-second emergency failsafe that removes any static IP (`192.168.1.116` / `192.168.0.116`) and restores automatic DHCP and DNS on `Ethernet` (physical Ethernet NIC). | Local PC Adapter (`Ethernet`) |
| **`Verify_All_Dumps_Chips_and_Backups.bat`** | Runs 81 cryptographic and structural checks across all flash dumps, bootloader/kernel headers, RF calibration (`xcap=27/46`, `RFE=6`), `vmlinux_stock.bin` `mib_table` keys, NVRAM configs, and backup archives. | Offline local files |

---

## Autonomous Post-Flash OpenWrt Provisioning (`Configure_OpenWrt_ISP_WAN_and_WiFi.bat` / `.ps1`)

### Purpose
When transitioning the Tenda AC10 V1.0 to Hybrid OpenWrt 4.14, the router boots with a default MAC address (`HW_NIC0_ADDR + 2`). Because the ISP binds internet access strictly to your registered/cloned WAN MAC (`wan1.macaddr`), internet connectivity will not function until the cloned WAN MAC is provisioned into OpenWrt. Furthermore, wireless radios default to generic or unconfigured states.

`Configure_OpenWrt_ISP_WAN_and_WiFi.bat` is a **100% autonomous, zero-configuration post-flash tool** that restores full ISP connectivity and wireless access in under 10 seconds without manual LuCI / SSH configuration.

### Zero-Argument Autonomous Workflow
1. Complete firmware flashing with `Flash_Hybrid_OpenWrt_4.14_TFTP.bat`.
2. Wait ~90–120 seconds for Hybrid OpenWrt 4.14 to boot. Your PC Ethernet adapter automatically receives an IP in `192.168.0.0/24` from OpenWrt DHCP.
3. Plug your ISP Ethernet cable into the **WAN port** (blue port / Switch Port 3).
4. Double-click **`Configure_OpenWrt_ISP_WAN_and_WiFi.bat`** (or run `powershell -ExecutionPolicy Bypass -File Configure_OpenWrt_ISP_WAN_and_WiFi.ps1`).
5. The tool automatically:
   - Locates `backups\RouterCfm_optimized_v1.cfg` (or sanitized configuration).
   - Extracts your cloned ISP WAN MAC (`wan1.macaddr`) and 2.4 GHz / 5 GHz Wi-Fi SSIDs and WPA2-PSK passwords.
   - Connects to OpenWrt at `192.168.0.1` via Windows built-in `ssh.exe` (`root@192.168.0.1`).
   - Executes UCI commands to set `network.wan.macaddr` and `network.wan_eth0_1_dev.macaddr`.
   - Configures Wi-Fi interfaces (SSID, WPA2-PSK encryption, enables radios).
   - Reloads network and wireless subsystems (`/etc/init.d/network reload` and `wifi reload`).
   - Verifies WAN interface status and reports leased IP.

### Command-Line Parameters
For custom setups or dry-run validation, the script supports explicit parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `-ConfigPath` | string | Auto-discovered | Path to `RouterCfm_optimized_v1.cfg` or sanitized config file |
| `-TargetIp` | string | `192.168.0.1` | IP address of OpenWrt router |
| `-SshUser` | string | `root` | SSH username |
| `-TargetPort` | int | `22` | SSH port |
| `-WanMac` | string | Auto-extracted | Override ISP WAN MAC address (e.g. `50:0F:F5:00:00:01`) |
| `-Ssid2G` | string | Auto-extracted | Override 2.4 GHz Wi-Fi SSID |
| `-Ssid5G` | string | Auto-extracted | Override 5 GHz Wi-Fi SSID |
| `-Key2G` | string | Auto-extracted | Override 2.4 GHz WPA2-PSK password (minimum 8 characters) |
| `-Key5G` | string | Auto-extracted | Override 5 GHz WPA2-PSK password (minimum 8 characters) |
| `-VerifyOnly` | switch | `false` | Parses config and validates parameters without network interaction |
| `-DryRun` | switch | `false` | Displays the generated UCI command sequence without SSH transmission |
| `-Force` | switch | `false` | Bypasses safety confirmations and allows fallback defaults |

### OPSEC & Information Safety
- Zero hardcoded credentials or MAC addresses in script source code.
- Console output masks Wi-Fi passwords (`******** (N chars)`) to protect credentials during screen sharing or logging.
- Fully compatible with sanitized configuration templates (`RouterCfm_optimized_sanitized.cfg`).

---

## Verified Hardware & Bootloader Facts (Reverse-Engineered from `booter_stage2_v3.4.11B.9_0x80000000.bin`)

1. **Bootloader Drops ICMP Ping (`0x80001010..0x80001018`)**:
   - Realtek Booter v3.4.11B.9 checks `ip_hdr[9] == 0x11` (UDP) and drops all ICMP packets. `ping 192.168.1.6` will **never** reply in bootloader mode. `Offline_TFTP_Recovery_and_Flash.ps1` probes `192.168.1.6:69` directly using RFC 1350 UDP TFTP `WRQ` packets.
2. **Switch Port 3 (WAN) Powered Down in Bootloader (`0x8000ec6c..0x8000ed58`)**:
   - `lan_wan_isolation` sets LAN mask `0xF7` and writes `0x0936` to PHY register `0x1B03` to power down Switch Port 3 (WAN). Always connect your Ethernet cable to **LAN1, LAN2, or LAN3** (Switch Ports 2, 1, or 0).
3. **`AutoBurn` (`0x800019d0`) & `check_image` (`0x8000dd10`)**:
   - Factory Stock TFTP image (`Tenda_AC10_V1_Stock_TFTP_Recovery.bin`, `7,588,884` B, SHA-256 `a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa`) uses 2-segment `cr6c` (`2,145,298` B) + `hsqs` (`5,443,586` B), both with 16-bit BE additive checksum `0x0000`.
   - Custom OpenWrt `cs6c` images **must be single-segment** (`file_size == 16 + seg_len`) because a 2-segment `cs6c` + `hsqs` image triggers a bootloader bug at `0x80001c2c` (`move $s7, $s2` with `$s2=0`) that erases flash offset `0x00000000`.
