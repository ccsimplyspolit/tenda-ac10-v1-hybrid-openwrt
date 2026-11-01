# Autonomous TFTP Disaster Recovery Protocol Specification

## 1. Protocol Architecture & Overview

The Realtek Booter (v3.4.11B.9) embedded in the Tenda AC10 V1.0 incorporates an autonomous **Emergency TFTP Server** designed to flash recovery firmware directly into SPI NOR flash without requiring serial UART console access or JTAG hardware adapters.

### Network Invariants:
- **Server IP Address**: `192.168.1.6` (Little-Endian `0x0601A8C0` stored at VA `0x8001A384`).
- **Subnet**: `192.168.1.0/24` (Subnet mask `255.255.255.0`).
- **Server MAC Address**: `50:0F:F5:00:00:01`.
- **Initial Listening Port**: UDP Port 69 (Big-Endian `0x0045`).
- **Transfer Protocol**: Standard RFC 1350 Trivial File Transfer Protocol (Octet / Binary mode).

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

---

## 2. Bootloader Network Quirks & Implementation Anomalies

Through static binary deconstruction of `booter_stage2_v3.4.11B.9_0x80000000.bin`, three unique protocol quirks have been cataloged:

### 2.1 Quirk 1: Unconditional Drop of Non-UDP Traffic (ICMP Ping Drop)
At VA `0x80001010`:
```assembly
0x80001010:  addiu    $v0, $zero, 0x11   # IPPROTO_UDP (17 decimal)
0x80001014:  lb       $v1, 9($s0)        # IPv4 Header Protocol Byte
0x80001018:  bne      $v1, $v0, 0x800011b4 # IF NOT UDP -> JUMP TO RETURN EPILOGUE!
```
- **Operational Reality**: The bootloader network engine contains no handler for ICMP. Ping packets sent to `192.168.1.6` are dropped without generating an ICMP Unreachable response.
- **Client Rule**: Client recovery utilities must **never** gate TFTP upload on ping responsiveness. Client software should resolve the router via ARP or directly transmit the TFTP Write Request.

### 2.2 Quirk 2: Physical Switch WAN Port Isolation
At VA `0x8000ED48`:
```assembly
0x8000ED48:  jal      0x8000e90c         # rtk_port_phy_power_down(3)
```
- The external WAN jack (connected to switch port 3) is explicitly powered down during bootloader initialization.
- **Client Rule**: The recovery host Ethernet cable must be plugged into **LAN Port 1, 2, or 3**. Plugging into the WAN port results in no Ethernet link.

### 2.3 Quirk 3: Ephemeral Source Port Switching
Following receipt of the initial TFTP WRQ packet on UDP port 69, the bootloader dynamically allocates an ephemeral UDP port (ranging between `1024` and `65535`) from which it emits all subsequent ACK packets:
- **Client Rule**: The client TFTP socket must dynamically bind to the source port indicated in the router's ACK 0 packet and direct subsequent DATA blocks to that ephemeral port.

---

## 3. The `AutoBurn` Verification Pipeline

Once the final TFTP DATA packet is received:
1. `AutoBurn` (`0x80001BC4`) compares the first 4 bytes of the image against the descriptor table at `0x8001722C`.
2. For stock firmware and multi-segment images, magic must be **`cr6c`** (`0x63723663`).
3. `check_image` (`0x8000DD10`) sums all 16-bit Big-Endian words modulo 65536. If `accum != 0x0000`, the booter halts and logs `"image checksum error at %X!"`.
4. It verifies that the declared payload length matches the received byte count. If trailing bytes exist, it loops into an infinite scan stall.
5. If valid, it writes the image to SPI Flash (`0x00030000` onward).
6. Upon write completion, it triggers an SoC watchdog reboot via `0xB8003000` bit 10.

---

## 4. Autonomous Client Implementation (RFC 1350 Compliant)

Below is the standalone Python TFTP upload engine (`tftp_emergency_engine.py`) designed to handle the Realtek Booter quirks:

```python
import socket, struct, time, os

def send_tftp_firmware(router_ip, firmware_path, local_ip="192.168.1.100"):
    assert os.path.exists(firmware_path), f"File {firmware_path} not found"
    with open(firmware_path, "rb") as f:
        file_data = f.read()
    total_bytes = len(file_data)
    print(f"[*] Uploading {firmware_path} ({total_bytes} bytes) to {router_ip}:69...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((local_ip, 0))
    sock.settimeout(3.0)

    # 1. Send WRQ (Opcode 2)
    filename = b"firmware.bin"
    mode = b"octet"
    wrq_packet = struct.pack(">H", 2) + filename + b"\x00" + mode + b"\x00"
    
    server_addr = (router_ip, 69)
    sock.sendto(wrq_packet, server_addr)

    # 2. Wait for ACK 0
    resp, server_addr = sock.recvfrom(1024)
    opcode, block_num = struct.unpack(">HH", resp[:4])
    assert opcode == 4 and block_num == 0, f"Expected ACK 0, got op={opcode}, block={block_num}"
    print(f"[+] Bootloader acknowledged WRQ. Connected to ephemeral port {server_addr[1]}.")

    # 3. Stream 512-byte blocks (RFC 1350 compliant with 0-byte termination)
    block = 1
    offset = 0
    while True:
        chunk = file_data[offset:offset + 512]
        data_packet = struct.pack(">HH", 3, block) + chunk
        
        acked = False
        for attempt in range(5):
            sock.sendto(data_packet, server_addr)
            try:
                resp, _ = sock.recvfrom(1024)
                ack_op, ack_block = struct.unpack(">HH", resp[:4])
                if ack_op == 4 and ack_block == block:
                    acked = True
                    break
            except socket.timeout:
                print(f"[-] Timeout on block {block}, retrying...")
                
        assert acked, f"Failed to transfer block {block} after 5 attempts."
        offset += len(chunk)
        if block % 500 == 0 or offset >= total_bytes:
            print(f"[*] Progress: {min(offset, total_bytes)}/{total_bytes} bytes ({(min(offset, total_bytes)/total_bytes)*100:.1f}%)")
        
        # RFC 1350 termination: block length < 512 signals end of transfer.
        # If total_bytes is an exact multiple of 512, an empty 0-byte block must be sent to terminate.
        if len(chunk) < 512:
            break
        block = (block + 1) & 0xFFFF

    print("[+] TFTP Upload Complete! Router is burning image into SPI flash...")
    print("[*] Please wait 60 seconds for automatic watchdog reboot.")
    sock.close()

if __name__ == "__main__":
    send_tftp_firmware("192.168.1.6", "Tenda_AC10_V1_Stock_TFTP_Recovery.bin")
```
