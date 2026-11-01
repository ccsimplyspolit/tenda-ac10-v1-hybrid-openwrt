import struct

FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"

with open(FLASH_PATH, "rb") as f:
    kdata = f.read()

base_addr = 0x80000000
table_offset = 0x005A2658 - 32 # let's check if there is an ALL partition right before Bootloader

print("=== MTD PARTITION TABLE PARSER FROM vmlinux_stock.bin ===")
for i in range(10):
    entry_off = table_offset + i * 32
    if entry_off + 32 > len(kdata):
        break
    name_ptr, pad, size, offset, mask, ecc = struct.unpack("<IIQQII", kdata[entry_off:entry_off+32])
    name_str = "NULL"
    if name_ptr >= base_addr and name_ptr - base_addr < len(kdata):
        str_start = name_ptr - base_addr
        str_end = kdata.find(b"\x00", str_start)
        if str_end != -1:
            name_str = kdata[str_start:str_end].decode(errors="ignore")
    print(f"Partition #{i:02d} (at offset 0x{entry_off:08X}):")
    print(f"  Name:       '{name_str}' (ptr: 0x{name_ptr:08X})")
    print(f"  Offset:     0x{offset:08X} ({offset} bytes)")
    print(f"  Size:       0x{size:08X} ({size} bytes, {size/1024:.1f} KB, {size/(1024*1024):.2f} MB)")
    print(f"  End:        0x{offset + size:08X}")
    print(f"  Mask Flags: 0x{mask:08X}")
    if name_ptr == 0:
        print("  [End of partition table reached]")
        break
