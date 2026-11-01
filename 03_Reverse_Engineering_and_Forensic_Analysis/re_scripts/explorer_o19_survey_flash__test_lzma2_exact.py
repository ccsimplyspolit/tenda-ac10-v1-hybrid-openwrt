import lzma

FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    data = f.read()

# Block 0 at 0x23BC72
block_start = 0x23BC72
block_end = 0x2472FE
raw_block = data[block_start:block_end]

payload = raw_block[24:]

# In XZ, at the end of the block there is:
# Block Padding (0 to 3 bytes of 0x00)
# Check (CRC32: 4 bytes)
# And then after the block comes:
# Index
# Stream Footer (12 bytes)
# So raw LZMA2 stream does NOT include the CRC32, Index, and Stream Footer!
print(f"Total payload size (including footer): {len(payload)} bytes")

# Let's test LZMADecompressor on payload with dict_size = 131072
decomp = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 131072}])

try:
    res = decomp.decompress(payload)
    print(f"SUCCESS! Decompressed {len(res)} bytes!")
    print(f"Decompressor finished: {decomp.eof}")
    print(f"Unused trailing bytes: {len(decomp.unused_data)} bytes")
    print(f"First 128 bytes of decompressed data:\n{res[:128]}")
except Exception as e:
    print(f"Decompress error: {e}")
