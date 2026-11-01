from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

    data = _load_vmlinux_stock()

# Let's check where non-zero data actually ends between 0x760000 and 0x790000
for i in range(0x780000, 0x760000, -1):
    if data[i-1] != 0:
        print(f"Last non-zero byte in kernel/rootfs partition is at 0x{i:06X} ({i})")
        print(f"Bytes right before end (0x{i-32:06X}): {data[i-32:i].hex()}")
        break

# Let's inspect the SquashFS superblock bytes_used again
sq_off = 0x23BC12
import struct
fields = struct.unpack("<IIIIIHHHHHHQQQQQQQQ", data[sq_off:sq_off+96])
bytes_used = fields[12]
print(f"SquashFS s_magic: {hex(fields[0])}")
print(f"SquashFS bytes_used: {bytes_used} (0x{bytes_used:X})")
print(f"sq_off + bytes_used = 0x{sq_off + bytes_used:06X}")
