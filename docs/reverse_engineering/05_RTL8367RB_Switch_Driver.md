# Realtek RTL8367RB-VB Switch Driver Deconstruction

## 1. Subsystem Architecture & Driver Scope

The Ethernet switching fabric of the Tenda AC10 V1.0 is controlled by the Linux kernel driver module `rtl8367r` (compiled directly into `vmlinux_stock.bin` at virtual addresses `0x801D7000`–`0x801DF000`). This driver serves three essential responsibilities:

1. **SMI Management Bus Implementation**: Bit-bangs Realtek's proprietary Serial Management Interface protocol over GPIO 18 and GPIO 19.
2. **Switch Chip Life-Cycle & Initialization**: Manages the hardware reset line (GPIO 58), configures RGMII clock delays, sets up internal packet buffers, and programs the 802.1Q VLAN filter table.
3. **CPU Tag Packet Demultiplexing**: Processes the 8-byte Realtek CPU Tag inserted by the switch on incoming frames, steering traffic to appropriate Linux netdevices (`eth0.1` for LAN, `eth0.2` for WAN).

```
+-----------------------------------------------------------------------------------+
|                        RTL8367RB Switch Driver Architecture                       |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | Linux Network Device Core (dev.c) / Packet Egress & Ingress (netif_rx)      |  |
|  +-----------------------------------------------------------------------------+  |
|                                        ^                                          |
|                                        | Clean 802.3 Frames (Stripped Tag)        |
|                                        v                                          |
|  +-----------------------------------------------------------------------------+  |
|  | Realtek CPU Tag Parser (RTL8367R_cpu_tag @ 0x801DB520)                      |  |
|  | - Ingress: Parses Byte 3 (Port 0=WAN, Ports 1..3=LAN) -> Dispatches to Netdev|  |
|  | - Egress:  Prepends 8-Byte Tag with Target Port Mask & Priority             |  |
|  +-----------------------------------------------------------------------------+  |
|                                        |                                          |
|                                        v                                          |
|  +-----------------------------------------------------------------------------+  |
|  | SMI Management Layer (smi_init @ 0x801D7B10 / smi_read / smi_write)        |  |
|  | - MDC Clock Generation (GPIO 18 / Port C2)                                  |  |
|  | - MDIO Bi-directional Data (GPIO 19 / Port C3)                              |  |
|  | - Hardware Chip Reset (GPIO 58 / Port H2)                                   |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 2. SMI Protocol Bit-Banging Driver Engine

Because the RTL8197FS SoC lacks a dedicated hardware MDIO master for external switches, the `rtl8367r` driver implements the bus entirely through GPIO toggling.

### 2.1 Low-Level Bit-Banging Primitives
Disassembly of `smi_read` (`0x801D73A0`) and `smi_write` (`0x801D7560`) reveals the precise timing loops:

```c
// Decompiled SMI Register Write Routine:
void rtl8367r_smi_write(uint32_t reg_addr, uint16_t reg_val) {
    // 1. Preamble: 32 cycles of MDC with MDIO pulled high (1)
    smi_set_mdio_dir_output();
    smi_set_mdio_high();
    for (int i = 0; i < 32; i++) {
        smi_clk_pulse(); // Pull MDC high, delay 1 us, pull MDC low, delay 1 us
    }

    // 2. Start of Frame (SOF): Pattern '01'
    smi_write_bit(0);
    smi_write_bit(1);

    // 3. Opcode: '01' for Register Write
    smi_write_bit(0);
    smi_write_bit(1);

    // 4. 16-bit Register Address (MSB First)
    for (int i = 15; i >= 0; i--) {
        smi_write_bit((reg_addr >> i) & 1);
    }

    // 5. Turnaround (TA): Pattern '10'
    smi_write_bit(1);
    smi_write_bit(0);

    // 6. 16-bit Payload Data (MSB First)
    for (int i = 15; i >= 0; i--) {
        smi_write_bit((reg_val >> i) & 1);
    }

    // 7. Bus Release (Z State)
    smi_set_mdio_dir_input();
}
```

### 2.2 Switch Reset Pin Probing (`rtl819x_8367r_reset_pin_probe` at `0x801DF824`)
At boot, the driver probes and claims the hardware reset pin (GPIO 58) for the RTL8367RB switch:
   ```assembly
   # Disassembly of rtl819x_8367r_reset_pin_probe (vmlinux_stock.bin: 0x801DF824):
   0x801df824:  addiu    $sp, $sp, -0x20
   0x801df828:  sw       $ra, 0x1c($sp)
   0x801df82c:  sw       $s1, 0x18($sp)
   0x801df830:  sw       $s0, 0x14($sp)
   0x801df834:  lw       $s1, 0x58($a0)        # Driver platform data (reset pin descriptor)
   0x801df838:  addiu    $a0, $a0, 0x10        # dev pointer
   0x801df83c:  lw       $a1, 0($s1)           # GPIO pin number (58)
   0x801df840:  addiu    $a2, $zero, 0x12      # GPIOF_DIR_OUT | GPIOF_EXPORT_DIR_FIXED
   0x801df844:  jal      0x8016036c            # devm_gpio_request_one
   0x801df848:  lw       $a3, 8($s1)           # Label string ("rtl8367r_reset")
   0x801df84c:  bltz     $v0, 0x801df870       # Branch on request error
   0x801df850:  move     $s0, $v0
   0x801df854:  lw       $v0, 4($s1)           # Active-low configuration flag
   0x801df858:  andi     $v0, $v0, 1
   0x801df85c:  beqz     $v0, 0x801df874
   0x801df860:  move     $v0, $s0
   0x801df864:  lw       $a0, 0($s1)
   0x801df868:  jal      0x801623c8            # gpio_sysfs_set_active_low
   0x801df86c:  addiu    $a1, $zero, 1
   ```
The driver configures GPIO 58 via `devm_gpio_request_one` (`0x8016036c`) as an output pin with initial level high, and registers sysfs active-low polarity via `gpio_sysfs_set_active_low` (`0x801623c8`). Once released from reset, the switch responds on SMI register `0x1300`.

---

## 3. Realtek CPU Tag Packet Demultiplexing (`0x801DB520`)

When frames traverse between GMAC0 and the switch, the driver inserts or strips the 8-byte CPU tag.

### Ingress Packet Processing (`RTL8367R_cpu_tag`):
```c
struct sk_buff *rtl8367r_rx_tag_demux(struct sk_buff *skb) {
    uint8_t *tag = skb->data + 12; // Tag follows Dest MAC (6 B) + Src MAC (6 B)

    // Check Realtek Tag Protocol ID
    uint16_t tag_tpid = (tag[0] << 8) | tag[1];
    if (tag_tpid != 0x8899) {
        return skb; // Pass untagged packets unchanged
    }

    // Extract physical source port index from Byte 3
    uint8_t source_port = tag[3] & 0x0F;

    // Shift Ethernet header 8 bytes forward to remove the CPU tag
    memmove(skb->data + 8, skb->data, 12);
    skb_pull(skb, 8); // Trim 8 bytes from buffer head

    // Map physical switch port to logical netdevice
    if (source_port == 0) {
        skb->dev = wan_netdev; // Port 0 is WAN (eth0.2)
    } else if (source_port >= 1 && source_port <= 3) {
        skb->dev = lan_netdev; // Ports 1..3 are LAN (eth0.1)
    }

    return skb;
}
```

---

## 4. Link Monitoring & Auto-Negotiation

The driver maintains a periodic 1-second kernel timer (`rtl8367r_link_timer` at `0x801DD420`) that polls PHY status registers:
- Reads PHY Status Register 1 (`0x0001`) across all 4 active PHYs (Port 0 through Port 3).
- Evaluates Link Status (Bit 2), Speed (10/100/1000 Mbps), and Duplex.
- On link state change (e.g. Ethernet cable inserted into LAN 1), executes `netif_carrier_on()` or `netif_carrier_off()`, notifying userspace network daemons (`multiWAN`, `dnsmasq`).
- Updates LED indicators on the front panel via SMI LED Control Registers (`0x0430`..`0x0438`).
