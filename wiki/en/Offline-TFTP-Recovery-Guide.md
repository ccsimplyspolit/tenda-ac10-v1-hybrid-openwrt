# Offline TFTP Disaster Recovery Guide & Playbook

This guide provides the complete, authoritative disaster recovery protocol for the **Tenda AC10 V1.0**. By utilizing the embedded emergency TFTP server built into the **Realtek Booter (v3.4.11B.9)**, any bricked, boot-looping, or misconfigured router can be fully restored to factory stock or upgraded to Hybrid OpenWrt 4.14 in under 3 minutes over standard ethernet—**without requiring serial UART soldering or JTAG hardware adapters**.

---

## 1. Protocol Architecture & Silicon Invariants

The Realtek Booter Stage 2 code contains an autonomous **Emergency TFTP Disaster Server**. When triggered, it initializes a minimalist networking stack and waits on UDP port 69 for a firmware image:

```
+-----------------------------------------------------------------------------------+
|               Realtek Booter TFTP Disaster Handshake Protocol                     |
|                                                                                   |
|     Recovery Client PC (192.168.1.100)            Router Booter (192.168.1.6:69)  |
|                     |                                           |                 |
|  [ARP Request]      |--- Who has 192.168.1.6? Tell 192.168.1.100-->| (0x80001280)    |
|  [ARP Reply]        |<-- 192.168.1.6 is at 50:0F:F5:00:00:01 ---| (0x800012C4)    |
|                     |                                           |                 |
|  [ICMP Echo Request]|--- Ping 192.168.1.6 (Type 8, Code 0) ---->| (0x80001010)    |
|                     |    *** SILENTLY DROPPED BY DESIGN! ***    | (No ICMP Code)  |
|                     |                                           |                 |
|  [TFTP WRQ]         |--- Write Request: "firmware.bin", octet ->| (UDP Port 69)   |
|  [TFTP ACK 0]       |<-- Block 0 Acknowledged (from port XXXXX)-| (Ephemeral Port)|
|                     |                                           |                 |
|  [TFTP DATA 1]      |--- Data Block 1 (512 Bytes) ------------->|                 |
|  [TFTP ACK 1]       |<-- Block 1 Acknowledged ------------------|                 |
|       ...           |                  ...                      |                 |
|  [TFTP DATA N]      |--- Final Block N (<= 512 Bytes) ---------->|                 |
|  [TFTP ACK N]       |<-- Final Block Acknowledged --------------|                 |
|                     |                                           |                 |
|  [AutoBurn Routine] |    Verifies cr6c header & additive csum   | (0x800019D0)    |
|                     |    Burns to Flash 0x00030000..0x0076CC14  |                 |
|  [Hardware Reset]   |    Watchdog Reboot (Reg 0xB8003000 Bit 10)| (0x80002244)    |
+-----------------------------------------------------------------------------------+
```

### Critical Silicon Rules & Quirk Warnings

1. **Rule 1: Silent ICMP Ping Drop (VA `0x80001010`)**:
   - The bootloader network loop drops all non-UDP traffic.
   - **Operational Reality**: Executing `ping 192.168.1.6` will **never** return a response. Recovery software must never wait for a ping reply before initiating TFTP upload.
2. **Rule 2: Physical WAN Port Isolation (VA `0x8000ECE8..0x8000ED4C`)**:
   - The bootloader initializes the RTL8367RB switch by explicitly cutting power to Physical Port 3 (the WAN jack) via `rtk_port_phy_power_down(3)`.
   - **Operational Reality**: You **MUST** connect your PC patch cable to **LAN Port 1, 2, or 3** (Ports 0..2 on the switch). Connecting to the WAN port will fail.
3. **Rule 3: Single-Segment Container Immunity (VA `0x80001C2C`)**:
   - The bootloader contains a flaw where multi-segment containers cause register `$s7` to be cleared to `0x00000000`, resulting in the second segment overwriting the `mtd0` bootloader.
   - **Operational Reality**: All official recovery binaries in this repository (`Tenda_AC10_V1_Stock_TFTP_Recovery.bin` and `tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin`) are packaged as single-segment `cs6c` images, guaranteeing 100% flashing immunity.

---

## 2. Entering Disaster Recovery Mode (The 15-Second Rule)

To place the router into the Realtek Booter emergency listener:

1. **Disconnect Cables**: Disconnect the WAN ethernet cable and power adapter.
2. **Connect PC**: Connect an ethernet cable between your PC's ethernet port and **LAN Port 1** on the router.
3. **Configure PC Static IP**:
   - **IP Address**: `192.168.1.100`
   - **Subnet Mask**: `255.255.255.0` (`/24`)
   - **Gateway / DNS**: Leave blank
4. **The 15-Second Power-On Hold (Method from 4PDA post #543)**:
   - Locate the **RST / WPS** button on the rear panel.
   - Press and hold the **RST / WPS** button firmly using a pen or paperclip.
   - While continuing to hold the button, insert the 12V power supply plug.
   - **Hold the button continuously for exactly 15 seconds**, then release.
5. **Validation**: The SYS LED will remain solid or blink slowly. The bootloader is now active and listening on `192.168.1.6:69`.

---

## 3. Autonomous 1-Click Recovery Suite (Windows)

This repository includes a 100% offline, standalone Python recovery suite located in `tools/autonomous_recovery/`:

```
tools/autonomous_recovery/
├── run_emergency_recovery.bat    # 1-Click automated execution script
├── flash_firmware.py             # High-level recovery workflow coordinator
├── tftp_emergency_engine.py      # Pure RFC 1350 compliant TFTP client
├── verify_firmware.py            # Pre-flash binary structure validator
├── restore_network.bat           # Failsafe script restoring PC to DHCP
└── backups/
    └── Tenda_AC10_V1_Stock_TFTP_Recovery.bin  # Clean 7.58 MB vendor stock recovery binary
```

### Execution Steps:
1. Double-click `tools/autonomous_recovery/run_emergency_recovery.bat`.
2. The automated script will:
   - Identify your active ethernet network adapter.
   - Safely save your existing network configuration.
   - Configure your adapter to static IP `192.168.1.100/24`.
   - Validate the integrity of `Tenda_AC10_V1_Stock_TFTP_Recovery.bin` (checking magic headers, length, and checksums).
   - Perform an ARP resolution handshake with the router at `192.168.1.6`.
   - Transmit the firmware over TFTP in 512-byte blocks.
   - Monitor transfer progress with a real-time progress bar.
   - Wait 120 seconds while the router burns the SPI Flash and reboots via hardware watchdog.
   - **Automatically restore your PC network adapter to its original DHCP settings**.

---

## 4. Manual Cross-Platform Recovery Procedures

If you prefer to perform the recovery manually without the automated suite:

### Method A: Linux / macOS Terminal
1. Configure your network interface (e.g. `eth0` or `enp3s0`):
   ```sh
   sudo ip addr add 192.168.1.100/24 dev eth0
   ```
2. Put the router into disaster mode (15-second hold).
3. Transmit the recovery binary using the standard `tftp` command line client (as pioneered by `vladisslav0` on 4PDA):
   ```sh
   echo -e 'binary\nput tools/autonomous_recovery/backups/Tenda_AC10_V1_Stock_TFTP_Recovery.bin\nquit\n' | tftp 192.168.1.6
   ```
4. Wait approximately 3 minutes for SPI flash writing and reboot.
5. Re-enable DHCP:
   ```sh
   sudo ip addr del 192.168.1.100/24 dev eth0
   sudo dhclient eth0
   ```

### Method B: Windows via Tftpd32 / Tftpd64
1. Configure Windows Ethernet adapter IPv4 properties:
   - `IP Address: 192.168.1.100`
   - `Subnet Mask: 255.255.255.0`
2. Download and launch `Tftpd64` (standard open-source edition).
3. Select the **Tftp Client** tab.
4. Set parameters:
   - **Host**: `192.168.1.6`
   - **Port**: `69`
   - **Local File**: Browse to `Tenda_AC10_V1_Stock_TFTP_Recovery.bin` (or `factory.bin`)
   - **Remote File**: Leave blank (or enter `firmware.bin`)
   - **Block Size**: `Default (512)`
5. Click **Put**.
6. The progress bar will advance as blocks are acknowledged. Once complete, wait 3 minutes.
7. Reset Windows Ethernet properties back to "Obtain an IP address automatically (DHCP)".

---

## 5. Recovery Verification & Troubleshooting Checklist

| Symptom / Observation | Root Cause | Verified Resolution |
|---|---|---|
| **TFTP client reports "Timeout" or "No response from server"** | PC connected to WAN jack, or PC IP is not `192.168.1.100` | 1. Move cable to LAN Port 1.<br>2. Confirm PC IP is `192.168.1.100/24`.<br>3. Re-enter disaster mode (hold RST for full 15s). |
| **`ping 192.168.1.6` fails with "Request timed out"** | Normal bootloader behavior | **Do not ping.** The bootloader intentionally drops ICMP at VA `0x80001010`. Proceed directly with TFTP upload. |
| **SYS LED blinks rapidly after flashing** | Flashing complete, router is performing initial filesystem mount | Wait 60 seconds. The router will initialize LAN ports on `192.168.0.1`. |
| **Router is unreachable at `192.168.0.1` after recovery** | PC adapter is still locked to static `192.168.1.100` | Reset PC ethernet adapter to DHCP. Execute `ipconfig /renew`. |
| **TFTP fails after exactly 32 MB transferred** | N/A (Firmware is only ~7.5 MB) | Firmware images are < 8 MB; block rollover occurs cleanly. |
