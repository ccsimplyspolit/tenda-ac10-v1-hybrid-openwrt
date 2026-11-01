# Master TFTP Flashing and Failsafe Recovery Guide: Tenda AC10 V1.0

This guide details the exact procedures for flashing Hybrid OpenWrt 4.14 firmware, performing emergency TFTP recovery, and restoring factory stock firmware + ISP WAN MAC (`<YOUR_WAN_MAC>`) without risk of permanent bricking or host PC network lockout.

> **PRIMARY RECOMMENDED METHOD:**
> Use the **Tenda AC10 V1.0 Autonomous Offline Recovery Suite** located in `K:\aoe4_dlc\Tenda_AC10_V1_Hybrid_Kit\offline_autonomous_tools\`.
> It operates 100% offline with zero external `pip` packages and no reliance on Windows optional `tftp.exe`, auto-detects the physical Ethernet adapter (`Intel(R) Ethernet Controller (3) I225-V`), guarantees automatic rollback to DHCP/DNS via `try / finally`, and pre-validates firmware images against the reverse-engineered Realtek Booter v3.4.11B.9 (`0x800019d0` `AutoBurn` and `0x8000dd10` `check_image`) requirements.

---

## 1. Hardware Architecture & Bootloader Environment

Reverse engineering of `mtd0_bootloader_0x000000_128KB.bin` (`0x000000`–`0x020000`) and `booter_stage2_v3.4.11B.9_0x80000000.bin` (`102,496` bytes, SHA-256 `569f298b243bfe0ef96684aaf342498c977276064e20840c5518a30ae3faf8d1`) confirmed:
- **Bootloader**: Realtek Booter `v3.4.11B.9` (LZMA/GZIP stage-2 payload loaded at `0x80000000`).
- **Default Recovery IP**: `192.168.1.6` (Subnet: `255.255.255.0`, Client IP accepted from any `192.168.1.x`).
- **TFTP Server Protocol**: UDP port 69, RFC 1350 TFTP **SERVER** mode (`0x8000189c`). Upon receiving a TFTP Write Request (`WRQ`, opcode `0x0002`), the bootloader latches the client IP/port and replies with `ACK 0` (`0x0004 0x0000`) from an ephemeral TID port starting at `2098` (`0x80019070`).
- **ICMP Ping Behavior (`0x80001010..0x80001018`)**: In `booter_stage2` (`0x80001010`), all non-UDP IPv4 packets ( anything other than IP protocol `0x11`, including ICMP Echo Request) are dropped. Therefore, `192.168.1.6` **NEVER responds to `ping` (`ping -t 192.168.1.6`)** in bootloader mode! Readiness is verified by sending a UDP TFTP `WRQ` packet to port `69` (assisted by ARP resolution at `0x80001280`) via `K:\aoe4_dlc\Tenda_AC10_V1_Hybrid_Kit\offline_autonomous_tools\Offline_TFTP_Recovery_and_Flash.bat`.
- **Ethernet Switch Mapping & WAN Port Isolation (`0x8000ECE8..0x8000ED4C`)**:
  - Disassembly of `booter_stage2` (`0x8000ECE8..0x8000ED4C`) proves that the WAN port (**Switch Port 3**) is isolated from the LAN bridge (`0xF7` mask) and its PHY is explicitly powered down (`PHY 3 reg 0 = 0x1940`, register `0x2060` via `0x1B03 = 0x0936`).
  - **CRITICAL**: During TFTP recovery, the Ethernet cable MUST be plugged **ONLY into LAN1, LAN2, or LAN3** (Switch Ports 2, 1, or 0), and **NEVER into the WAN port (Switch Port 3)**.
- **RAM Execution Buffer**: `0x80A00000` (cached) / `0xA0A00000` (uncached).
- **Burn Destination**: `0x00030000` (Offset 192 KB), strictly preserving Bootloader at `0x000000..0x020000` (128 KB) and Factory RF Calibration MTD1 at `0x020000..0x030000` (64 KB).
- **Maximum Flash Capacity**: `8,060,928` bytes (7,872 KB, `0x7B0000`). Any image exceeding this boundary will corrupt the CFM NVRAM partitions at `0x7E0000`.
- **Checksum & Segment Rules (`AutoBurn` `0x800019d0` & `check_image` `0x8000dd10`)**:
  - 16-bit Big-Endian additive checksum modulo 65536 across payload must equal `0x0000`.
  - Factory stock recovery (`Tenda_AC10_V1_Stock_TFTP_Recovery.bin`, `7,588,884` B) uses a 2-segment `cr6c` (`2,145,298` B) + `hsqs` (`5,443,586` B) layout.
  - OpenWrt images with `cs6c` magic **MUST be single-segment** (`file_size == 16 + seg_len`). A 2-segment `cs6c` + `hsqs` image triggers a bug at `0x80001c2c` (`move $s7, $s2` with `$s2=0`) that erases flash offset `0x00000000`. Our offline tools automatically detect and block multi-segment `cs6c` images before touching the network.
- **Hardware Reset Button**: GPIO 54 (`PEFGH_DAT` `0xB8003528` bit 22), active-low, debounced over 8 cycles. Triggers `"Entry disaster mode"`.

---

## 2. Recommended Method: Autonomous Offline Recovery Suite

All scripts are self-contained inside `K:\aoe4_dlc\Tenda_AC10_V1_Hybrid_Kit\offline_autonomous_tools\`:

### 2.1 Reverting to Clean Stock Firmware via TFTP
1. Connect your PC Ethernet cable to **LAN1, LAN2, or LAN3** on the router (NOT WAN).
2. Double-click `K:\aoe4_dlc\Tenda_AC10_V1_Hybrid_Kit\offline_autonomous_tools\Offline_TFTP_Recovery_and_Flash.bat` (or pass a custom firmware image path).
3. Click **Yes** on the Windows UAC elevation prompt.
4. Put the router into TFTP Disaster Recovery Mode:
   - Unplug 12V DC power from the router.
   - Hold the **RST** button on the rear panel.
   - Plug 12V DC power back in while continuing to hold **RST** for **6 to 10 seconds** until the SYS LED blinks rapidly.
   - Release **RST**.
5. The script automatically:
   - Verifies `backups\Tenda_AC10_V1_Stock_TFTP_Recovery.bin` (`7,588,884` B, SHA-256 `a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa`),
   - Saves your current NIC state to `network_state_backup.json` and sets temporary static IP `192.168.1.116/24`,
   - Streams all 14,823 TFTP blocks to `192.168.1.6:69`,
   - Waits for the SPI NOR flash burn to complete, and
   - Unconditionally restores your PC Ethernet adapter (`Intel I225-V`) back to automatic **DHCP + DNS** inside a `finally` block.

### 2.2 Restoring Optimized Stock+ Config & ISP WAN MAC (`<YOUR_WAN_MAC>`)
Once the router boots into stock firmware at `192.168.0.1` (even if you have zero internet access because the factory reset wiped the cloned WAN MAC):
1. Double-click `K:\aoe4_dlc\Tenda_AC10_V1_Hybrid_Kit\offline_autonomous_tools\Restore_Optimized_Config_and_WAN.bat`.
2. It validates `backups\RouterCfm_optimized_v1.cfg` (`25,369` B, SHA-256 `078243bc81190d7012c6d3b1f9dd8d00c70ea6c4e7b23dc1bbbe373e0d02b9bd`), authenticates to `http://192.168.0.1/login/Auth`, and uploads the configuration to `/cgi-bin/UploadCfg`.
3. After ~45 seconds, the router reboots with `wan1.macaddr=<YOUR_WAN_MAC>`, `iptv.stb.enable=0` (no `br2`/`vlan3`), `ucloud.syncserver=0`, `sys.maxconn=8192`, and `sys.timentpserver=time.google.com`.

### 2.3 Flashing Hybrid OpenWrt 4.14
Drag-and-drop your compiled single-segment `cs6c` factory image onto `Offline_TFTP_Recovery_and_Flash.bat`, or run from PowerShell/CMD:
```cmd
"K:\aoe4_dlc\Tenda_AC10_V1_Hybrid_Kit\offline_autonomous_tools\Offline_TFTP_Recovery_and_Flash.bat" "path\to\openwrt-rtl8197f-tenda-ac10-v1-squashfs-factory.bin"
```

### 2.4 Emergency One-Click PC Network Restoration
If power is lost or a terminal window is forcibly closed during static IP mode:
- Double-click `K:\aoe4_dlc\Tenda_AC10_V1_Hybrid_Kit\offline_autonomous_tools\Emergency_Restore_PC_Network_DHCP.bat`.
- It immediately removes any residual static `192.168.1.x` / `192.168.0.x` IP and restores automatic DHCP and DNS on your physical Ethernet adapter.

---

## 3. Alternative Flashing: UART Serial Console (3.3V TTL, 115200 8N1)

### 3.1 Pinout Header
Locate the 4-pin UART pad row on the Tenda AC10 V1 PCB:
- **Pin 1 (Square pad)**: VCC 3.3V (**LEAVE DISCONNECTED**)
- **Pin 2**: TX (Connect to USB-UART RX)
- **Pin 3**: RX (Connect to USB-UART TX)
- **Pin 4**: GND (Connect to USB-UART GND)

### 3.2 Bootloader Prompt (`<RealTek>`)
1. Open serial terminal at `115200` baud, 8N1, no flow control.
2. Power on the router and press `ESC` or `SPACE` within 3 seconds to enter `<RealTek>`.
3. Push the firmware from the host PC using `Offline_TFTP_Recovery_and_Flash.bat` (auto-burns to `0x00030000`).

---

## 4. Hardware SPI Programmer Unbrick (CH341A / SOIC-8 Clip)

If the bootloader partition (`0x000000..0x020000`) is ever physically damaged:
1. Attach a 3.3V SOIC-8 clip to the **Winbond W25Q64JV/FV** (JEDEC ID `0xEF4017`, 8,388,608 bytes) SPI NOR chip.
2. Write the bit-for-bit verified full flash image:
   ```bash
   flashrom -p ch341a_spi -c "W25Q64.V" -w "K:\aoe4_dlc\Tenda_AC10_V1_Hybrid_Kit\backups\Tenda_AC10_V1_FullFlash_8MB.bin"
   ```
   - Expected Size: `8,388,608` bytes
   - Expected SHA-256: `af40888b2a92539ef51218a7ed6dc25c48ac2cd51950ffcf25bec44b98252833`
