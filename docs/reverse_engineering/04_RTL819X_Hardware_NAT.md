# Realtek RTL819X / RTL865X Hardware NAT ASIC Architecture

## 1. Executive Acceleration Overview

The Realtek RTL8197FS SoC embeds a dedicated **Hardware Network Address Translation (HW NAT) ASIC Offload Engine**—historically designated across Realtek BSP codebases as `rtl819x_hwnat` or `rtl865x`. This engine sits directly on the silicon bus between the Gigabit Ethernet Media Access Controller (GMAC0) and the integrated memory controller, providing line-rate Layer 2, Layer 3, and Layer 4 packet processing.

### Key Performance Capabilities
- **IPv4 Wire-Speed Forwarding**: 895 Mbps to 940 Mbps bidirectional throughput for IPoE / DHCP WAN connections.
- **CPU Offload**: Reduces CPU utilization from 100% (software forwarding capped at ~140 Mbps) down to **0.0% to 1.5%** during multi-hundred-megabit routing.
- **Hardware NAPT Flow Capacity**: 1024 concurrent active hardware offloaded 5-tuple flows (Table `0x09`).
- **Hardware Functions Accelerated**: L2 MAC learning/aging, 802.1Q VLAN filtering, IPv4 checksum calculation, TCP/UDP port mapping, TTL decrement, and ARP gateway resolution.

```
+-----------------------------------------------------------------------------------+
|                        RTL8197FS Hardware NAT Data Flow                           |
|                                                                                   |
|        Incoming Packet from WAN/LAN Physical Port (via RTL8367RB Port 6)          |
|                                        |                                          |
|                                        v                                          |
|  +-----------------------------------------------------------------------------+  |
|  | GMAC0 Receive FIFO -> Table Lookup Unit (TLU Engine @ 0xBB804418)           |  |
|  | - Extracts Layer 2/3/4 Header: (Proto, SrcIP, DstIP, SrcPort, DstPort)     |  |
|  | - Hardware CRC/Hash Computation over 5-tuple                                |  |
|  +-----------------------------------------------------------------------------+  |
|                                        |                                          |
|                        +---------------+---------------+                          |
|                        |                               |                          |
|                 [Hardware HIT]                  [Hardware MISS]                   |
|                        |                               |                          |
|                        v                               v                          |
|  +-----------------------------------+   +-------------------------------------+  |
|  | FastPath ASIC Rewrite Engine      |   | Push Frame to Linux sk_buff Queue   |  |
|  | - Table 0x09: Rewrite IP & Port   |   | - FastPath_Enter (0x8047306c)       |  |
|  | - Table 0x02/0x07: Update MACs    |   | - Linux Netfilter Conntrack Core    |  |
|  | - Hardware Checksum Recalculation |   | - IPS_CONFIRMED State Reached       |  |
|  | - Direct Egress to GMAC0 Tx Ring  |   | - rtl865x_handle_nat (0x8047DC20)   |  |
|  |                                   |   | - Installs Flow into ASIC Table 0x09|  |
|  | Result: 940 Mbps Wire-Speed Rate  |   +-------------------------------------+  |
|  | CPU Overhead: 0.0%                |                                            |
|  +-----------------------------------+                                            |
+-----------------------------------------------------------------------------------+
```

---

## 2. Linux Netfilter Hook Integration

In `vmlinux_stock.bin`, the HW NAT subsystem attaches directly to standard Linux Netfilter conntrack hooks via `rtl_nat_init_hooks` (located at `0x8047F57C` and registered into the netfilter hook table at `0x804BC9FC`).

### Key Driver Entry Points:
1. **`FastPath_Enter` (`0x8047306c`)**:
   - Intercepts raw incoming frames before standard Linux protocol stack traversal.
   - Evaluates packet validity and queries whether the flow already possesses an active ASIC table entry.
2. **`FastPath_Route` (`0x8046E770`)**:
   - Queries the on-silicon routing cache to determine outgoing interface and next-hop MAC.
3. **`rtl865x_handle_nat` (`0x8047DC20`)**:
   - Invoked when a transit connection transitions to `IPS_CONFIRMED` in `nf_conntrack`.
   - Extracts the 5-tuple, calculates hardware hash indices, and calls `_rtl8651_forceAddAsicEntry` to offload the flow.

---

## 3. ASIC Table Types & Memory Layout

The HW NAT engine manages eight dedicated hardware tables indexed by type identifier:

| Table ID | Table Name | Entry Size | Description & Capacity |
|---|---|---|---|
| **`0x00`** | L2 FDB Unicast Table | 2 words (8 Bytes) | Layer 2 MAC address forwarding database (1024 entries) |
| **`0x02`** | ARP Gateway Table | 3 words (12 Bytes) | Resolved IP-to-MAC associations and physical switch port targets |
| **`0x04`** | Net Interface Table | 5 words (20 Bytes) | Physical / VLAN interface descriptors, MTUs, and base MACs |
| **`0x05`** | PPPoE Session Table | 3 words (12 Bytes) | PPPoE session IDs, server MACs, and hardware encapsulation tags |
| **`0x07`** | Routing Table | 3 words (12 Bytes) | L3 subnet prefixes, netmasks, and NextHop table indices |
| **`0x09`** | NAPT Flow Table | 3 words (12 Bytes) | 5-tuple TCP/UDP NAT translation entries (1024 hardware slots) |
| **`0x0B`** | NextHop Table | 1 word (4 Bytes) | Intermediate gateway indices pointing to ARP table entries |
| **`0x0C`** | VLAN Filter Table | 11 words (44 Bytes) | 4096-entry 802.1Q hardware VLAN membership and egress tagging |

---

## 4. Hardware MMIO Programming Pipeline

The kernel driver programs these tables via memory-mapped I/O registers in the GMAC0 block. Disassembly of `_rtl8651_forceAddAsicEntry` (`0x801D8C90`) exposes the mandatory synchronization protocol:

```assembly
# Disassembly of _rtl8651_forceAddAsicEntry (vmlinux_stock.bin: 0x801D8C90):
# 1. Pause Table Lookup Unit (TLU) Pipeline (Assert Bit 18 = 0x00040000):
0x801D8C90: 80 bb 02 3c  lui      $v0, 0xbb80
0x801D8C94: 18 44 42 34  ori      $v0, $v0, 0x4418
0x801D8C98: 00 00 44 8c  lw       $a0, ($v0)
0x801D8C9C: 04 00 03 3c  lui      $v1, 4             # 0x00040000 = (1 << 18)
0x801D8CA0: 25 18 83 00  or       $v1, $a0, $v1
0x801D8CA4: 00 00 43 ac  sw       $v1, ($v0)

# 2. Poll until TLU indicates pipeline is fully halted (Bit 19 = 0x00080000):
0x801D8CA8: 21 20 40 00  move     $a0, $v0
0x801D8CAC: 08 00 03 3c  lui      $v1, 8             # 0x00080000 = (1 << 19)
0x801D8CB0: 00 00 82 8c  lw       $v0, ($a0)
0x801D8CB4: 24 10 43 00  and      $v0, $v0, $v1
0x801D8CB8: fd ff 40 10  beqz     $v0, 0x801d8cb0    # Loop until halted

# 3. Issue Write Command (Opcode 3 = Force Add) to TABLE_ACCESS_CTRL (0xBB804D00):
0x801D8CBC: 80 bb 02 3c  lui      $v0, 0xbb80
0x801D8CC0: 03 00 03 24  addiu    $v1, $zero, 3
0x801D8CC4: 00 4d 42 34  ori      $v0, $v0, 0x4d00
0x801D8CC8: 00 00 43 ac  sw       $v1, ($v0)

# 4. Poll Busy Bit until Hardware completes write:
0x801D8CCC: 21 18 40 00  move     $v1, $v0
0x801D8CD0: 00 00 62 8c  lw       $v0, ($v1)
0x801D8CD4: 01 00 42 30  andi     $v0, $v0, 1        # Check Bit 0 (Busy Bit)
0x801D8CD8: fd ff 40 14  bnez     $v0, 0x801d8cd0    # Loop until write finishes
```

---

## 5. Critical OpenWrt Hybrid 4.14 Porting Requirements

Porting `rtl819x_hwnat` to modern OpenWrt 19.07 (Linux 4.14) historically failed for two subtle architectural reasons solved by the Hybrid Kit:

### 5.1 Requirement 1: `PORT0_ROUTER_MODE` (Switch Port Tagging)
Under legacy bridge mode, all external switch ports enter GMAC0 untagged. As a result, the ASIC treats ingress and egress as occurring on the same logical port, dropping routed packets as hairpins.
- **Fix**: The driver must enable Realtek CPU Port Tagging (`REG32(MACCR1) |= PORT0_ROUTER_MODE`). This maps physical WAN to ASIC Port 0 and physical LANs to ASIC Ports 1..3, allowing the HW NAT engine to establish valid cross-port hardware forwarding vectors.

### 5.2 Requirement 2: The Numeric Host-Byte-Order Fix
The RTL8197F ASIC table registers and hardware hash generators evaluate IP addresses and TCP/UDP ports as **numeric host-order integers**, NOT network-order big-endian octet streams.
- Legacy Realtek SDK code written for big-endian MIPS performed `htonl()` on addresses. When compiled for little-endian MIPS (`mipsel`), this reversed the byte order twice, causing hash mismatch and silent hardware lookup failures.
- **Fix**: Ensure all IP addresses and port numbers passed to `TABLE_DATA0..2` maintain native host-byte-order (`mipsel` little-endian), enabling instantaneous 100% hardware flow matching.
