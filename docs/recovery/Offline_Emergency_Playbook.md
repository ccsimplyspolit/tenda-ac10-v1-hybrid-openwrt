# Tenda AC10 V1.0 Offline Emergency Disaster Recovery Playbook

## 1. Playbook Mission & Overview

This document provides the definitive, battle-tested, **solderless disaster recovery playbook** for restoring a bricked, bootlooping, corrupted, or unreachable Tenda AC10 V1.0 router.

### Guarantee of Non-Destructive Solderless Recovery:
Because the Realtek Booter (Stage 1 and Stage 2) resides in protected flash sectors (`0x000000 - 0x00020000`), software misconfigurations, corrupted OpenWrt builds, or interrupted firmware flashes cannot destroy the bootloader. By triggering the hardware disaster recovery hook, the router can always be restored to 100% operational condition using standard Ethernet cables without opening the plastic chassis or soldering serial UART headers.

```
+-----------------------------------------------------------------------------------+
|               5-Step Solderless Disaster Recovery Pipeline                        |
|                                                                                   |
|  [Step 1: Physical Cabling]       --> Connect PC to LAN 1 (Yellow Port)           |
|                                       (DO NOT use Blue WAN Port - it is disabled!)|
|                                                                                   |
|  [Step 2: Host Network Config]    --> Set PC Static IP: 192.168.1.100 / 24        |
|                                                                                   |
|  [Step 3: Hardware Disaster Mode] --> Hold Reset Button -> Insert Power Barrel    |
|                                       Hold for 5-7 Seconds -> Release             |
|                                                                                   |
|  [Step 4: Image Upload]           --> Upload Tenda_AC10_V1_Stock_TFTP_Recovery.bin|
|                                       via Autonomous TFTP Engine to 192.168.1.6   |
|                                                                                   |
|  [Step 5: Post-Flash Reboot]      --> Wait 60s for AutoBurn & Watchdog Reboot     |
|                                       Set PC back to DHCP -> Access 192.168.0.1   |
+-----------------------------------------------------------------------------------+
```

---

## 2. Step 1: Physical Hardware Cabling

1. Disconnect all Ethernet cables currently attached to the router.
2. Connect one standard Category 5e/6 Ethernet cable directly between your computer's Ethernet port and router **LAN Port 1 (Yellow Jack 1)**.
3. **CRITICAL WARNING**: Do **NOT** connect the cable to the Blue WAN Jack. As proven in bootloader disassembly (`0x8000ED48`), the bootloader explicitly powers down Switch Port 3 (WAN PHY) during disaster mode. Connecting to WAN produces no electrical carrier.

---

## 3. Step 2: Host Network Interface Configuration

The Realtek Booter listens exclusively at IP `192.168.1.6`. Your computer must be placed on the identical subnet:

### Windows Configuration (PowerShell as Administrator):
```powershell
# Identify your Ethernet adapter name
Get-NetAdapter | Where-Object Status -eq 'Up'

# Configure Static IP 192.168.1.100 on adapter "Ethernet"
New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress "192.168.1.100" -PrefixLength 24 -DefaultGateway "192.168.1.6"

# Temporarily disable Windows Firewall to prevent blocking ephemeral UDP ACKs
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False
```

*(Remember to re-enable Windows Firewall once recovery is complete!)*

---

## 4. Step 3: Triggering Hardware Disaster Mode

1. Unplug the 12V 1.5A DC power barrel connector from the router rear panel.
2. Using a paperclip or SIM card ejector, press and hold the physical **Reset pushbutton** located inside the small pinhole on the router rear.
3. While continuing to hold the Reset button down firmly, insert the 12V power barrel connector.
4. Keep the Reset button depressed for **5 to 7 seconds**:
   - Observe the front panel LEDs. The SYS and WPS LEDs will illuminate solid or blink in unison.
5. Release the Reset button.
6. The router is now parked in Realtek Booter Stage 2 emergency recovery mode, actively serving UDP port 69.

### Important Note on ICMP Ping:
**DO NOT ATTEMPT TO PING 192.168.1.6!** As proven in reverse engineering observation 1.1.2 (`0x80001010`), the bootloader drops all ICMP packets. `ping 192.168.1.6` will return `"Request timed out"`. You can verify connection readiness by checking the Windows ARP table:
```cmd
arp -a
```
Look for `192.168.1.6` associated with physical MAC `50-0f-f5-00-00-01`.

---

## 5. Step 4: Flashing the Recovery Firmware

### 5.1 Approved Recovery Firmware Binary
You must flash the clean, verified recovery image:
- **Filename**: `Tenda_AC10_V1_Stock_TFTP_Recovery.bin`
- **File Size**: `7,588,884` bytes
- **SHA-256**: `a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa`

**LETHAL TRAP WARNING**: Never upload the raw partition dump `mtd3_kernelfs.bin` (8,060,928 bytes). That raw dump contains 472 KB of trailing dirty JFFS2 bytes that trigger an infinite header scan loop in `AutoBurn`, permanently stalling the flashing process!

### 5.2 Upload Execution via Autonomous Recovery Suite
Run the autonomous recovery tool:

```powershell
# Method A: Using the One-Click Emergency Recovery Launcher
.\tools\autonomous_recovery\run_emergency_recovery.bat

# Method B: Using the Python Emergency Engine directly
python tools/autonomous_recovery/tftp_emergency_engine.py
```

The tool will:
1. Locate `Tenda_AC10_V1_Stock_TFTP_Recovery.bin`.
2. Transmit the 14,822 UDP blocks over port 69.
3. Display real-time transfer progress (`0% -> 100%`).
4. Complete the transfer in approximately 12–15 seconds.

---

## 6. Step 5: SPI Burning & Automatic Reboot

1. Once the upload finishes, **DO NOT POWER OFF THE ROUTER**.
2. The bootloader `AutoBurn` routine begins writing the image into SPI flash memory sectors.
3. Wait **60 full seconds**.
4. The router triggers a hardware watchdog reset and reboots automatically.
5. Restore your computer network adapter to DHCP:
   ```powershell
   Set-NetIPInterface -InterfaceAlias "Ethernet" -Dhcp Enabled
   Remove-NetRoute -InterfaceAlias "Ethernet" -Confirm:$False
   Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True
   ```
6. Open your web browser and move to:
   `http://192.168.0.1`
7. The router displays the factory setup wizard. Your Tenda AC10 V1.0 is 100% restored!

---

## 7. Troubleshooting & Failure Diagnostics

| Symptom | Underlying Root Cause | Definitive Remediation |
|---|---|---|
| `ping 192.168.1.6` times out | Bootloader protocol filter drops non-UDP at `0x80001010` | Ignore ping. Run `arp -a` to confirm MAC `50:0F:F5:00:00:01` |
| Ethernet interface shows "Network cable unplugged" | Cable connected to Blue WAN Jack (powered down at `0x8000ED48`) | Move Ethernet cable to Yellow LAN Port 1 |
| TFTP transfer fails with "Timeout on block 0" | Windows Firewall blocking incoming ephemeral UDP ACK packets | Temporarily disable Windows Firewall during flashing |
| Transfer reaches 100% but router never reboots | Image contains trailing padding bytes or invalid checksum | Use verified `Tenda_AC10_V1_Stock_TFTP_Recovery.bin` |
| Router boots but WAN port cannot connect to ISP | Factory recovery restored default MAC; ISP requires cloned MAC | Run `Restore_Optimized_Config_and_WAN.bat` to restore cloned MAC |
