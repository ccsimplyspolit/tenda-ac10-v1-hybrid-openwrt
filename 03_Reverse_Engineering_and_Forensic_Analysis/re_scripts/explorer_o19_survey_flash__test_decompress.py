import lzma
import zlib

FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    data = f.read()

# First block at 0x23BC72.
# How long is the compressed block?
# The second block was found at 0x2472FE!
# Length = 0x2472FE - 0x23BC72 = 46732 bytes (0xB68C bytes).
block_start = 0x23BC72
block_end = 0x2472FE
raw_block = data[block_start:block_end]
print(f"Block 0: length = {len(raw_block)} bytes")
header = raw_block[:24]
payload = raw_block[24:]
print(f"Header: {header.hex()} | {header}")
print(f"Payload first 32 bytes: {payload[:32].hex()}")

# Try different decompressors
# 1. Try lzma FORMAT_RAW with FILTER_LZMA2 with dictionary sizes (e.g. 64KB, 128KB, 1MB, 2MB, etc.)
for dict_size in [1 << 16, 1 << 17, 1 << 18, 1 << 19, 1 << 20, 1 << 21, 1 << 22, 1 << 23, 1 << 24]:
    try:
        decomp = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": dict_size}])
        res = decomp.decompress(payload)
        print(f"[SUCCESS LZMA2] dict_size={dict_size}: decompressed {len(res)} bytes! Unconsumed: {len(decomp.unused_data)}")
        print(f"First 64 bytes of decompressed: {res[:64]}")
        break
    except Exception as e:
        # print(f"dict_size {dict_size} failed: {e}")
        pass

# 2. Try lzma FORMAT_XZ (maybe it has an XZ stream?)
try:
    res = lzma.decompress(payload, format=lzma.FORMAT_XZ)
    print(f"[SUCCESS FORMAT_XZ] {len(res)} bytes")
except Exception as e:
    pass

# 3. Try standard lzma (FORMAT_ALONE)
try:
    res = lzma.decompress(payload, format=lzma.FORMAT_ALONE)
    print(f"[SUCCESS FORMAT_ALONE] {len(res)} bytes")
except Exception as e:
    pass

# 4. Try from byte 0 (including header?)
for dict_size in [1 << 16, 1 << 17, 1 << 18, 1 << 19, 1 << 20, 1 << 21, 1 << 22]:
    try:
        decomp = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": dict_size}])
        res = decomp.decompress(raw_block)
        print(f"[SUCCESS LZMA2 raw_block] dict_size={dict_size}: decompressed {len(res)} bytes")
        break
    except Exception as e:
        pass
