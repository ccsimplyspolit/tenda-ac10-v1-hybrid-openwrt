import struct
import datetime

FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    data = f.read()

sq_off = 0x23BC12
sq_hdr = data[sq_off:sq_off+96]

fields = struct.unpack("<IIIIIHHHHHHQQQQQQQQ", sq_hdr[:96])
magic, inodes, mkfs_time, block_size, fragments, compression, block_log, flags, no_ids, s_major, s_minor = fields[:11]
root_inode, bytes_used, id_table, xattr_table, inode_table, dir_table, frag_table, lookup_table = fields[11:]

comp_names = {1: "gzip", 2: "lzma", 3: "lzo", 4: "xz", 5: "lz4", 6: "zstd"}
print(f"Superblock at 0x{sq_off:06X}:")
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
print(f"  Bytes used: {bytes_used} (0x{bytes_used:X} bytes, {bytes_used/(1024*1024):.2f} MB)")
print(f"  Inode table start: 0x{sq_off + inode_table:06X} (rel: 0x{inode_table:X})")
print(f"  Dir table start:   0x{sq_off + dir_table:06X} (rel: 0x{dir_table:X})")
print(f"  Frag table start:  0x{sq_off + frag_table:06X} (rel: 0x{frag_table:X})")
print(f"  ID table start:    0x{sq_off + id_table:06X} (rel: 0x{id_table:X})")
print(f"  End of SquashFS:   0x{sq_off + bytes_used:06X}")

post_sb = data[sq_off+96:sq_off+96+128]
print(f"\nBytes immediately after superblock (0x{sq_off+96:06X}):")
for r in range(0, 128, 16):
    chunk = post_sb[r:r+16]
    hex_str = " ".join(f"{b:02X}" for b in chunk)
    asc_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
    print(f"  +0x{r:04X}: {hex_str:<48} | {asc_str}")

# Search for the custom "Tenda" header mentioned in prompt
tenda_magic = b"Tenda\x00"
pos = sq_off
found = 0
print(f"\nSearching for '{tenda_magic}' in SquashFS region:")
while found < 10:
    idx = data.find(tenda_magic, pos)
    if idx == -1 or idx > sq_off + bytes_used:
        break
    header_chunk = data[idx:idx+32]
    print(f"  Found '{tenda_magic}' at 0x{idx:06X} (rel 0x{idx-sq_off:06X}): {header_chunk[:24].hex()} | {header_chunk[:24]}")
    pos = idx + 1
    found += 1
