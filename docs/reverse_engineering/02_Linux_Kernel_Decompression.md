# Linux Kernel Extraction, Decompression & Early Boot Analysis

## 1. Overview & Image Container Structure

On the Tenda AC10 V1.0 router, the operating system kernel is stored in SPI Flash partition `mtd3` starting at address `0x00030000`. The binary consists of a proprietary Realtek **`cr6c`** 16-byte container header followed immediately by an LZMA-compressed MIPS32 Linux 3.10.90 kernel payload.

### Binary Artifact Details
- **Carved Kernel Binary**: `kernel_cr6c_0x030000.bin`
- **Total File Size**: 2,145,298 bytes (16 bytes header + 2,145,282 bytes LZMA payload).
- **Cryptographic Hash (SHA-256)**: `023bc89c65c7c0c00ee6ca34b65c07644c3df62f3c38e76e760bcef54248dd33`.
- **Flash Boundary**: `0x00030000` to `0x0023BC12`.
- **Decompressed Kernel (`vmlinux`)**: 7,253,712 bytes (ELF executable / raw binary).
- **Decompressed Kernel Hash (SHA-256)**: `9fe866e2bb67a5b48700fcdbaceeeb393a0698aee0a07ff85f50386c430225d2`.

```
+-------------------------------------------------------------------------------+
|         Tenda AC10 V1.0 cr6c Kernel Container Layout (2,145,298 Bytes)        |
+-------------------+-------------------+-------------------+-------------------+
| Magic (4 Bytes)   | Target Addr (4 B) | Checksum + Flag   | Payload Len (4 B) |
| "cr6c" (0x63723663)| 0x00030000        | 0xXXXX (16-bit)   | 0x0020BC02 (BE)   |
+-------------------+-------------------+-------------------+-------------------+
|                                                                               |
|                   LZMA Compressed Kernel Payload (2,145,282 Bytes)            |
|                   - Properties: 0x5D (lc=3, lp=0, pb=2)                       |
|                   - Dictionary: 8 MB (0x00800000)                             |
|                   - Uncompressed: 7,253,712 Bytes (Linux 3.10.90)             |
|                                                                               |
+-------------------------------------------------------------------------------+
```

---

## 2. The 16-Byte `cr6c` Header Specification

The Realtek Booter identifies, verifies, and flashes kernel images using a specialized 16-byte descriptor header:

| Byte Offset | Field Name | Data Type | Value in Stock Image | Functional Purpose |
|---|---|---|---|---|
| `0x00 - 0x03` | `magic` | 4-byte ASCII | `0x63 0x72 0x36 0x63` (`cr6c`) | Image signature: Linux kernel with attached rootfs |
| `0x04 - 0x07` | `burn_addr` | `uint32_be` | `0x00030000` | Target SPI flash programming offset |
| `0x08 - 0x09` | `checksum` | `uint16_be` | `0x5B5E` (Variable) | 16-bit additive checksum field |
| `0x0A - 0x0B` | `flags` | `uint16_be` | `0x0000` | Header flags / compression type |
| `0x0C - 0x0F` | `length` | `uint32_be` | `0x0020BC02` (2,145,282 B) | Exact payload length in bytes excluding the 16-byte header |

### 2.1 The 16-Bit Big-Endian Additive Checksum Algorithm
In `booter_stage2_v3.4.11B.9` (`check_image` at `0x8000DD10`), the integrity verification loops across all 16-bit words of the image:

```c
// Decompiled Additive Checksum Verification Algorithm:
uint16_t verify_image_checksum(const uint8_t *buffer, size_t total_length) {
    uint32_t sum = 0;
    const uint16_t *words = (const uint16_t *)buffer;
    size_t count = total_length / 2;

    for (size_t i = 0; i < count; i++) {
        // Words are read in Big-Endian format
        uint16_t word = (buffer[i * 2] << 8) | buffer[i * 2 + 1];
        sum = (sum + word) & 0xFFFF;
    }

    // A valid image must sum to 0x0000 modulo 65536
    return (uint16_t)sum;
}
```

If `sum != 0x0000`, the booter halts with `"image checksum error at %X!"`.

---

## 3. LZMA Decompression Mechanics

Starting at offset `0x10` of `kernel_cr6c_0x030000.bin`, the byte stream is a raw LZMA container:
- **Byte 0 (Header 0x10)**: `0x5D` — Encodes LZMA properties:
  - `pb = 0x5D / 45 = 2` (position bits)
  - `0x5D % 45 = 4`
  - `lp = 4 / 9 = 0` (literal position bits)
  - `lc = 4 % 9 = 3` (literal context bits)
- **Bytes 1..4 (Header 0x11..0x14)**: `0x00 0x00 0x80 0x00` (Little-Endian: 8 MB dictionary size).
- **Bytes 5..12 (Header 0x15..0x1C)**: `0x90 0xED 0x6E 0x00 0x00 0x00 0x00 0x00` (Little-Endian: declared uncompressed length = `7,253,712` bytes = `0x006EED90`).

### Python Extraction Script
```python
import struct, lzma

with open("kernel_cr6c_0x030000.bin", "rb") as f:
    raw_data = f.read()

# Verify cr6c magic
magic, burn_addr, csum, flags, payload_len = struct.unpack(">4sIHHI", raw_data[:16])
assert magic == b"cr6c", f"Invalid magic: {magic}"
print(f"Target Flash Offset: {hex(burn_addr)}")
print(f"Declared Payload Length: {payload_len} bytes")

# Extract LZMA payload
lzma_payload = raw_data[16:16 + payload_len]

# Decompress raw LZMA stream
decomp = lzma.decompress(lzma_payload)
print(f"Decompressed Kernel Size: {len(decomp)} bytes")

with open("vmlinux_stock.bin", "wb") as out:
    out.write(decomp)
```

---

## 4. Kernel Architecture & Symbol Reconstruction

The uncompressed binary `vmlinux_stock.bin` is a 32-bit Little-Endian MIPS Linux kernel:
- **Kernel Version**: Linux 3.10.90 (`Linux version 3.10.90 (root@localhost) (gcc version 4.4.7) #1 SMP PREEMPT`).
- **Target CPU**: MIPS 24KEc V5.0 FPU-less.
- **Execution Entry Point**: `0x80480860` (`kernel_entry`).
- **Load Address**: `0x80000000` (KSEG0 cached DRAM).

### 4.1 Symbol Table Extraction (`kallsyms`)
From `vmlinux_stock.bin`, the entire embedded Linux symbol table was forensically recovered, yielding **31,434 symbols** cataloged in `kallsyms_stock_31434.txt`:

```
0x80480860 T kernel_entry
0x806be698 T start_kernel
0x801a8fd0 t rtkxxpart_parse
0x801d7b10 T smi_init
0x801d8958 T _rtl8651_readAsicEntry
0x801d8bbc T _rtl8651_forceAddAsicEntry
0x801df888 t rtl819x_8367r_i2c_pin_probe
0x8024c5ec T odm_SetCrystalCap
0x80264810 T phydm_init_hw_info_by_rfe_type_8822b
0x80372380 T halmac_parse_efuse_data_88xx
0x8047306c T FastPath_Enter
0x8047dc20 T rtl865x_handle_nat
0x805a2638 d rtl819x_parts
0x805f96bc d mib_table
```

---

## 5. Early Boot Sequence Execution Flow

Upon handover from Stage 2 at `0x80480860`:
1. **Cache & MMU Flush**: Initializes MIPS CP0 Config registers and invalidates L1 I-Cache and D-Cache lines.
2. **Clear BSS**: Zeroes memory from `_edata` to `_end` (`0x805A2000`–`0x806B8000`).
3. **`prom_init` (`0x806BF2A0`)**:
   - Parses boot arguments passed from Stage 2.
   - Detects system memory size (configures `max_pfn = 0x4000`, 64 MB physical DDR2).
4. **Subsystem Probing**:
   - `smi_init`: Configures switch SMI GPIO lines.
   - `pci_scan_bus`: Detects RTL8822BE on PCIe RC0.
   - `rtkxxpart_parse`: Probes SPI Flash and registers MTD partitions.
   - Mounts RootFS at `0x0023BC12` and executes `/sbin/init`.
