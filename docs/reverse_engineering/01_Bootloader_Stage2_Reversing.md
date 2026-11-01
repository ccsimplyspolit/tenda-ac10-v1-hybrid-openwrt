# Realtek Booter Stage 2 Disassembly & Protocol Reverse Engineering

## 1. Overview & Binary Provenance

The primary bootloader of the Tenda AC10 V1.0 is based on **Realtek Booter v3.4.11B.9**, tailored for the Realtek RTL8197F family. The bootloader architecture employs a two-stage execution model:

1. **Stage 1 Bootloader (ROM / SPI XIP)**:
   - Stored in SPI NOR Flash sector 0 (`0x000000 - 0x00007D60`).
   - Executes directly out of the SPI Execute-In-Place (XIP) memory window at `0xBFC00000`.
   - Configures CPU PLL clocks, initializes DDR2 SDRAM timing registers at `0xB8001000`, and locates the compressed Stage 2 payload at flash offset `0x00007D60`.
   - Decompresses the GZIP stream into physical DRAM at base `0x00000000` (length: 102,496 bytes).
   - Transfers control to KSEG0 entry point `0x80000000`.

2. **Stage 2 Bootloader (`booter_stage2_v3.4.11B.9_0x80000000.bin`)**:
   - **File Size**: 102,496 bytes.
   - **Cryptographic Hash (SHA-256)**: `569f298b243bfe0ef96684aaf342498c977276064e20840c5518a30ae3faf8d1`.
   - **Target Architecture**: MIPS32 Release 2, Little-Endian (`mipsel`).
   - **Execution Base**: `0x80000000` (KSEG0 cached DRAM).
   - **Responsibilities**: Memory diagnostics, emergency network stack (ARP, UDP, TFTP Server), hardware watchdog arming, SPI flash burning engine (`AutoBurn`), and kernel bootstrapping.

```
       +----------------------------------------------------------------+
       |   Realtek Booter v3.4.11B.9 Execution Flow & Memory Layout     |
       |                                                                |
       |  0x80000000: Entry Point (b 0x8000040C)                        |
       |               |                                                |
       |               v (Exception Vector Table: 0x80000008-0x80000408)|
       |  0x8000040C: System Init: CP0 Setup, $sp=0x80700000             |
       |               CP0 Status interrupt mask, Count/Compare/Watch=0 |
       |               |                                                |
       |               v                                                |
       |  0x80000DF8: Network Stack Init: IP = 192.168.1.6 (0x0601A8C0) |
       |               MAC = 50:0F:F5:00:00:01                          |
       |               |                                                |
       |               v                                                |
       |  0x8000ECE8: Switch Init: Power-Down Port 3 (Physical WAN)     |
       |               Enable Ports 0, 1, 2 (Physical LAN 1, 2, 3)      |
       |               |                                                |
       |               +-----------------------+                        |
       |               |                       |                        |
       |     [TFTP Disaster Mode]        [Normal Boot]                  |
       |               |                       |                        |
       |               v                       v                        |
       |       UDP Port 69 Server        Verify cr6c Image at 0x030000  |
       |       AutoBurn Flashing         Decompress Kernel to 0x80002000|
       |       Watchdog Reboot           Jump to kernel_entry           |
       +----------------------------------------------------------------+
```

---

## 2. Entry Point, Memory Initialization, and Stack Setup

Disassembly of the Stage 2 entry vector reveals standard MIPS runtime setup:

```assembly
# Entry Vector at 0x80000000:
0x80000000: 02 01 00 10  b        0x8000040c         # Branch over exception vectors (MIPS word 0x10000102)
0x80000004: 00 00 00 00  nop
0x80000008 .. 0x80000408:  nop                      # Reserved space for MIPS32 exception table

# Initialization Routine at 0x8000040C:
0x8000040C: 00 90 80 40  mtc0     $zero, $18, 0      # CP0 WatchHi = 0
0x80000410: 00 98 80 40  mtc0     $zero, $19, 0      # CP0 WatchLo = 0
0x80000414: 00 68 80 40  mtc0     $zero, $13, 0      # CP0 Cause = 0
0x80000418: 00 60 08 40  mfc0     $t0, $12, 0        # Read CP0 Status
0x8000041C: 00 10 01 3c  lui      $at, 0x1000
0x80000420: 1f 00 21 34  ori      $at, $at, 0x1f     # Mask interrupts (bits 4..0)
0x80000424: 25 40 01 01  or       $t0, $t0, $at
0x80000428: 1f 00 08 39  xori     $t0, $t0, 0x1f
0x8000042C: 00 60 88 40  mtc0     $t0, $12, 0        # Write CP0 Status
0x80000430: c0 00 00 00  ehb
0x80000434: 00 48 80 40  mtc0     $zero, $9, 0       # CP0 Count = 0
0x80000438: 00 58 80 40  mtc0     $zero, $11, 0      # CP0 Compare = 0
0x8000043C: 70 80 1d 3c  lui      $sp, 0x8070        # $sp initialized to 0x80700000
```

- **Stack Allocation**: The booter initializes its execution stack pointer to `0x80700000` (`lui $sp, 0x8070`), utilizing high DRAM headroom for execution frames.
- **Interrupts & CP0**: MIPS CP0 WatchHi/WatchLo (`$18`, `$19`), Cause (`$13`), Count (`$9`), and Compare (`$11`) registers are zeroed. CP0 Status register `$12` has bits 4..0 cleared (interrupts masked), followed by an Execution Hazard Barrier (`ehb`), running the bootloader in pure polled mode.

---

## 3. Disaster TFTP Server & The ICMP Ping Drop Defect

When the router enters recovery mode (either via hardware pushbutton held during power-on or when firmware checksum validation fails), Stage 2 launches an embedded TFTP server.

### 3.1 Network Configuration
- **Hardcoded Recovery IP**: `192.168.1.6`
- **Default Subnet Mask**: `255.255.255.0`
- **Default Router MAC Address**: `50:0F:F5:00:00:01`
- **Listening UDP Port**: Port 69 (Big-Endian `0x0045`)

Disassembly at `0x80000DF8`–`0x80000E00` confirms the IP assignment:
```assembly
0x80000DF8:  0106033c  lui      $v1, 0x0601
0x80000DFC:  c0a86334  ori      $v1, $v1, 0xa8c0   # $v1 = 0x0601a8c0 (Little-Endian 192.168.1.6)
0x80000E00:  84a343ac  sw       $v1, -0x5c7c($v0)  # Store to 0x8001A384
```

### 3.2 The ICMP Drop Defect (`0x80001010`)
Many automated recovery tools fail because they ping `192.168.1.6` to verify device connectivity before initiating a TFTP transfer. The disassembly of the booter IPv4 parser explains why this fails:

```assembly
0x80001010:  11000224  addiu    $v0, $zero, 0x11   # $v0 = 0x11 (IPPROTO_UDP, 17 decimal)
0x80001014:  09000382  lb       $v1, 9($s0)        # Read byte 9 of IPv4 header (Protocol field)
0x80001018:  66006214  bne      $v1, $v0, 0x800011b4 # IF PROTOCOL != UDP, JUMP TO DROP!
...
0x800011B4:  1800b08f  lw       $s0, 0x18($sp)     # Function epilogue
0x800011B8:  0800e003  jr       $ra                # Immediate return: packet dropped
0x800011BC:  2000bd27  addiu    $sp, $sp, 0x20
```

**Forensic Finding**: The Realtek Booter IPv4 parser possesses **no code path for ICMP** (`IPPROTO_ICMP` = `0x01`). If an incoming packet's protocol byte is anything other than `0x11` (UDP), instruction `0x80001018` immediately branches to the return epilogue. **ICMP Echo Requests (ping) are 100% dropped by design**. Recovery software must communicate via ARP and UDP without waiting for ping replies.

---

## 4. Physical Switch Port Isolation in Bootloader Mode

A secondary hardware trap exists in the booter's switch initialization routine (`0x8000ECE8`–`0x8000ED4C`):

```assembly
0x8000ECE8:  addiu    $s4, $zero, 3      # Select Port 3 (Physical WAN Port)
0x8000ECEC:  j        0x8000ecfc
0x8000ECF0:  addiu    $s5, $zero, 1
0x8000ECF4:  addiu    $s1, $s1, 1        # Next port
0x8000ECF8:  addiu    $s2, $s2, 1
0x8000ECFC:  beq      $s1, $s4, 0x8000ecf4 # IF port_idx == 3 -> SKIP PORT ENABLE!
0x8000ED00:  move     $a0, $s1           # Enable LAN ports 0, 1, 2
0x8000ED04:  jal      0x8000df00         # rtk_port_enable(port_idx)
...
0x8000ED48:  jal      0x8000e90c         # rtk_port_phy_power_down(3) -> DISABLE WAN PHY!
0x8000ED4C:  addiu    $a0, $zero, 3
```

**Forensic Finding**: The bootloader explicitly powers down Switch Port 3 (connected to the external WAN jack). If an Ethernet cable is plugged into the WAN port, the PHY layer is electrically disabled—no link pulses or carrier detect will occur. **Flashing must be performed via LAN Ports 1, 2, or 3**.

---

## 5. `AutoBurn` Flashing Engine & Binary Vulnerability Analysis

Once a firmware binary is received over UDP port 69, Stage 2 invokes `AutoBurn` (`0x80001BC4`–`0x800022E8`).

### 5.1 Image Header Descriptor Table (`0x8001722C`)
`AutoBurn` compares the first 4 bytes of incoming segments against an 8-entry descriptor table:

| Descriptor | Magic (Hex) | ASCII | Target Flash Address | Checksum Required | Description |
|---|---|---|---|:---:|---|
| Entry 0 | `0x63733663` | `cs6c` | `0x00030000` | Yes | Linux Kernel (Stand-alone) |
| Entry 1 | `0x63723663` | `cr6c` | `0x00030000` | Yes | Linux Kernel with RootFS |
| Entry 2 | `0x77366367` | `w6cg` | `0x00020000` | No | Webpages / Static UI |
| Entry 3 | `0x72366372` | `r6cr` | `0x00100000` | No | Root Filesystem (Standalone) |
| Entry 4 | `0x626f6f74` | `boot` | `0x00000000` | Yes | Bootloader Update |
| Entry 5 | `0x414c4c31` | `ALL1` | `0x00000000` | Yes | Full Flash Image (with check) |
| Entry 6 | `0x414c4c32` | `ALL2` | `0x00000000` | No | Full Flash Image (no check) |
| Entry 7 | `0x68737173` | `hsqs` | `0x00100000` | No | SquashFS Superblock |

### 5.2 The Lethal `$s7` Zeroing Bug (`0x80001C2C`)
A severe defect in the Realtek Booter `AutoBurn` logic occurs when multi-segment images attempt to chain `cs6c` and `hsqs` headers:

```assembly
0x80001C14:  lw       $a1, 0x50($sp)     # Magic string "hsqs"
0x80001C18:  jal      memcmp
0x80001C1C:  addiu    $a2, $zero, 4
0x80001C20:  beqz     $v0, 0x80001c30    # Branch if match
0x80001C24:  addiu    $v0, $s3, 0x10
0x80001C28:  j        0x80001c3c
0x80001C2C:  move     $s7, $s2           # CRITICAL DEFECT: $s7 = $s2 (delay slot)
```

1. Register `$s2` is initialized to `0` at function entry.
2. The delay slot instruction at `0x80001C2C` unconditionally copies `$s2` (`0`) into `$s7`.
3. Later at `0x80002298`:
   ```assembly
   0x80002298:  move     $s2, $s7          # $s2 is forced to 0
   ```
4. Register `$s2` is the index into the descriptor table. Forcing `$s2 = 0` causes the second segment (RootFS) to be processed as Entry 0 (`cs6c`), resetting the target flash write address back to `0x00030000`.
5. **Consequence**: The RootFS payload is written directly over the kernel at `0x00030000`, corrupting the kernel and bricking the router!
6. **Remediation**: All multi-segment recovery images **must use `cr6c`** (Entry 1), which handles kernel and rootfs as a unified contiguous stream.

### 5.3 The Trailing Padding Infinite Loop Stall
At `0x800022B8`:
```assembly
0x800022B0:  addiu    $s4, $s5, 0x10     # Next header candidate offset
0x800022B4:  lw       $v1, 0xbc($sp)     # Total uploaded file size
0x800022B8:  sltu     $v0, $s4, $v1      # while (processed_bytes < total_bytes)
0x800022BC:  bnez     $v0, 0x80001ad0    # Loop back to parse trailing bytes
```
If an image file contains trailing padding bytes (such as JFFS2 residue or 0xFF alignment), `AutoBurn` attempts to parse the padding as a new image header. When no matching descriptor is found, it loops infinitely without rebooting. Images must be strictly trimmed to exact payload size.

### 5.4 Hardware Watchdog Auto-Reboot (`0x80002234`)
Upon successful burn, Stage 2 triggers a hardware reset:
```assembly
0x80002234:  lui      $v0, 0xb800
0x80002238:  ori      $v0, $v0, 0x3000   # RTL8197F System Reset Register (0xB8003000)
0x8000223C:  lw       $v1, ($v0)
0x80002240:  ori      $v1, $v1, 0x0400   # Assert Bit 10 (Global SoC Reset Trigger)
0x80002244:  sw       $v1, ($v0)         # Immediate reboot!
```
