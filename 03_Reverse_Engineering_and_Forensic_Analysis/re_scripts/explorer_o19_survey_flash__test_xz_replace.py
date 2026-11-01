import lzma

from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

    data = _load_vmlinux_stock()

# First block at 0x23BC72
block_start = 0x23BC72
block_end = 0x2472FE
raw_block = data[block_start:block_end]

# 1. Test replacing Tenda\x00 with \xfd7zXZ\x00
standard_xz_header = b"\xfd7zXZ\x00"
test_block = standard_xz_header + raw_block[6:]

try:
    decomp = lzma.decompress(test_block)
    print(f"SUCCESS with direct header replacement! Decompressed {len(decomp)} bytes!")
    print(f"First 64 bytes: {decomp[:64]}")
except Exception as e:
    print(f"Direct replacement failed: {e}")

# 2. What about the footer?
# In XZ, the stream footer is:
# CRC32 (4 bytes)
# Backward Size (4 bytes)
# Stream Flags (2 bytes)
# Footer Magic (2 bytes): 'YZ' (0x59 0x5A)
# Let's check the last 12 bytes of raw_block!
print("Last 16 bytes of block 0:", raw_block[-16:].hex())
print("Last 16 bytes repr:", raw_block[-16:])
