import struct
import datetime

from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

    data = _load_vmlinux_stock()

print("="*60)
print(f"FLASH ANALYSIS: Total size = {len(data)} bytes ({len(data)/(1024*1024)} MB)")
print("="*60)

# --- 1. BOOTER (0x00000 - 0x20000) ---
booter = data[0x0:0x20000]
print("\n[PARTITION 0: BOOTER / U-BOOT]")
print(f"Range: 0x000000 - 0x020000 (128 KB)")
# Extract printable strings of length >= 6
strings = []
cur = []
for b in booter:
    if 32 <= b <= 126:
        cur.append(chr(b))
    else:
        if len(cur) >= 6:
            strings.append("".join(cur))
        cur = []
print(f"Sample booter strings (first 30):")
for s in strings[:30]:
    print(f"  {s}")

# Check for specific U-boot environment or version strings in booter
env_strings = [s for s in strings if any(k in s.lower() for k in ["boot", "ver", "eth", "tftp", "mac", "ip", "rtl819", "realtek"])]
print(f"\nKey boot / network strings in booter:")
for s in env_strings[:20]:
    print(f"  {s}")

# --- 2. MTD1 / FACTORY RF CALIBRATION (0x20000 - 0x30000) ---
mtd1 = data[0x20000:0x30000]
print("\n" + "="*60)
print("[PARTITION 1: MTD1 / FACTORY CALIBRATION]")
print(f"Range: 0x020000 - 0x030000 (64 KB)")
print(f"Header 64 bytes hex:\n{mtd1[:64].hex()}")

# Let's inspect strings or key-value pairs in mtd1
mtd1_strings = []
cur = []
offset = 0
for i, b in enumerate(mtd1):
    if 32 <= b <= 126:
        cur.append(chr(b))
    else:
        if len(cur) >= 4:
            str_val = "".join(cur)
            mtd1_strings.append((i - len(cur), str_val))
        cur = []

print(f"\nExtracted strings in mtd1 ({len(mtd1_strings)} total):")
for off, s in mtd1_strings:
    print(f"  [+0x{off:04X} / Abs: 0x{0x20000+off:06X}] {s}")

# Check binary layout of mtd1
# Let's see non-string regions:
print("\nHex dump of first 256 bytes of mtd1:")
for row in range(0, 256, 16):
    chunk = mtd1[row:row+16]
    hex_str = " ".join(f"{b:02X}" for b in chunk)
    ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
    print(f"  +0x{row:04X} (0x{0x20000+row:06X}): {hex_str:<48} | {ascii_str}")

# --- 3. KERNEL (0x30000 - 0x23BC12) ---
print("\n" + "="*60)
print("[PARTITION 2: KERNEL]")
print(f"Range: 0x030000 - 0x23BC12 ({0x23BC12 - 0x30000} bytes / {(0x23BC12 - 0x30000)/1024:.2f} KB)")
khdr = data[0x30000:0x30040]
print("Kernel header (64 bytes):")
for row in range(0, 64, 16):
    chunk = khdr[row:row+16]
    hex_str = " ".join(f"{b:02X}" for b in chunk)
    ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
    print(f"  +0x{row:04X}: {hex_str:<48} | {ascii_str}")

# Parse Realtek cr6c / cs6c header:
# signature: 4 bytes
# load_addr: 4 bytes
# start_addr: 4 bytes
# image_size: 4 bytes
sig, load_addr, start_addr, img_len = struct.unpack(">4sIII", khdr[:16])
print(f"Header parsed (big-endian):")
print(f"  Signature: {sig}")
print(f"  Load Addr: 0x{load_addr:08X}")
print(f"  Start Addr: 0x{start_addr:08X}")
print(f"  Image Len: 0x{img_len:08X} ({img_len} bytes)")
print(f"  Calculated end of kernel: 0x{0x30000 + img_len:06X} (Diff from Squashfs: 0x{0x23BC12 - (0x30000 + img_len):X} bytes)")

# --- 4. SQUASHFS (0x23BC12 - EOF) ---
print("\n" + "="*60)
print("[PARTITION 3: ROOTFS / SQUASHFS]")
sq_off = 0x23BC12
sq_hdr = data[sq_off:sq_off+96]
print(f"Superblock at 0x{sq_off:06X} (96 bytes):")
magic, inodes, mkfs_time, block_size, fragments, compression, block_log, flags, no_ids, s_major, s_minor, root_inode, bytes_used, id_table, xattr_table, inode_table, dir_table, frag_table, lookup_table = struct.unpack(
    "<IIIIHH HHHHQQQQQQQQ"[::1].replace(' ', ''), sq_hdr[:96]
)

comp_names = {1: "gzip", 2: "lzma", 3: "lzo", 4: "xz", 5: "lz4", 6: "zstd"}
print(f"  Magic: {hex(magic)} ({chr(magic&0xff)}{chr((magic>>8)&0xff)}{chr((magic>>16)&0xff)}{chr((magic>>24)&0xff)})")
print(f"  Inodes: {inodes}")
print(f"  Mkfs Time: {datetime.datetime.fromtimestamp(mkfs_time, tz=datetime.timezone.utc)} ({mkfs_time})")
print(f"  Block size: {block_size} bytes (log2: {block_log})")
print(f"  Fragments: {fragments}")
print(f"  Compression ID: {compression} ({comp_names.get(compression, 'unknown')})")
print(f"  Flags: 0x{flags:04X}")
print(f"  ID count: {no_ids}")
print(f"  Version: {s_major}.{s_minor}")
print(f"  Root inode ref: 0x{root_inode:016X}")
print(f"  Bytes used: {bytes_used} (0x{bytes_used:X} bytes, ~{bytes_used/(1024*1024):.2f} MB)")
print(f"  Calculated SquashFS end: 0x{sq_off + bytes_used:06X}")
print(f"  Total flash capacity: 0x{len(data):06X}")
print(f"  Free / Unused flash at end: {len(data) - (sq_off + bytes_used)} bytes ({(len(data) - (sq_off + bytes_used))/1024:.2f} KB)")
