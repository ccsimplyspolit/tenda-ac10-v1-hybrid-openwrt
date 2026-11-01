import os
import struct

FLASH_PATH = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

def analyze_flash():
    with open(FLASH_PATH, "rb") as f:
        data = f.read()

    print(f"Total flash size: {len(data)} bytes ({len(data)/(1024*1024):.2f} MB)")

    # 1. Booter check (0x0 to 0x20000)
    booter = data[0:0x20000]
    print(f"\n--- 1. BOOTER (0x00000 - 0x20000, {len(booter)} bytes) ---")
    print(f"First 16 bytes: {booter[:16].hex()}")
    # Search for known boot strings
    for s in [b"U-Boot", b"Realtek", b"RTL8197", b"Booter", b"TFTP", b"baudrate", b"bootcmd", b"bootargs"]:
        pos = 0
        while True:
            idx = booter.find(s, pos)
            if idx == -1:
                break
            # print surrounding string
            start = max(0, idx - 10)
            end = min(len(booter), idx + 50)
            clean_str = booter[start:end].replace(b'\x00', b' ')
            print(f"  Match for {s.decode(errors='ignore')} at 0x{idx:05X}: {clean_str}")
            pos = idx + len(s) + 20
            if pos >= len(booter) or idx > 0x10000:
                break

    # 2. mtd1 check (0x20000 to 0x30000)
    mtd1 = data[0x20000:0x30000]
    print(f"\n--- 2. MTD1 / FACTORY / CALIBRATION (0x20000 - 0x30000, {len(mtd1)} bytes) ---")
    print(f"First 32 bytes (hex): {mtd1[:32].hex()}")
    print(f"First 32 bytes (repr): {mtd1[:32]}")
    # Check for magic signatures: 'HS', 'HW', 'WLAN', 'TE', MAC addresses, etc.
    non_ff = sum(1 for b in mtd1 if b != 0xff and b != 0x00)
    print(f"Non-00/FF bytes count: {non_ff} / {len(mtd1)}")

    # 3. Kernel check (around 0x30000)
    print(f"\n--- 3. KERNEL HEADER (around 0x30000) ---")
    kernel_hdr = data[0x30000:0x30040]
    print(f"0x30000 64 bytes hex: {kernel_hdr.hex()}")
    print(f"0x30000 64 bytes repr: {kernel_hdr}")

    # Check for signatures around 0x30000: 'cs6c', 'cr6c', uImage magic 0x27051956
    for off in range(0x2ff00, 0x30100, 4):
        chunk = data[off:off+4]
        if chunk in [b'cs6c', b'cr6c', b'\x27\x05\x19\x56']:
            print(f"  Found signature {chunk} at 0x{off:06X}")

    # 4. SquashFS check (around 0x23bc12)
    print(f"\n--- 4. SQUASHFS HEADER ---")
    sqfs_pos = data.find(b"hsqs")
    while sqfs_pos != -1:
        print(f"Found 'hsqs' magic at 0x{sqfs_pos:06X} (decimal {sqfs_pos})")
        # inspect header
        hdr = data[sqfs_pos:sqfs_pos+96]
        print(f"  Header bytes: {hdr[:32].hex()}")
        # Squashfs 4.0 superblock struct:
        # uint32_t s_magic (0x73717368)
        # uint32_t inodes
        # uint32_t mkfs_time
        # uint32_t block_size
        # uint32_t fragments
        # uint16_t compression (1=gzip, 2=lzma, 3=lzo, 4=xz, 5=lz4, 6=zstd)
        # uint16_t block_log
        # uint16_t flags
        # uint16_t no_ids
        # uint16_t s_major
        # uint16_t s_minor
        if len(hdr) >= 32:
            magic, inodes, mkfs_time, block_size, fragments, compression, block_log, flags, no_ids, s_major, s_minor = struct.unpack("<IIIIHHH HHHH"[::1].replace(' ', ''), hdr[:28]) # let's unpack carefully
            print(f"  magic={hex(magic)}, inodes={inodes}, mkfs_time={mkfs_time}, block_size={block_size}, fragments={fragments}, compression={compression}, major={s_major}, minor={s_minor}")
        sqfs_pos = data.find(b"hsqs", sqfs_pos + 4)

analyze_flash()
