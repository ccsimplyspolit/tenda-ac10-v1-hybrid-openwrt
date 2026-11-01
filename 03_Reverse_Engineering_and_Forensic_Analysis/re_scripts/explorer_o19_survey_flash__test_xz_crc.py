import lzma
import binascii

FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    data = f.read()

block_start = 0x23BC72
block_end = 0x2472FE
raw_block = data[block_start:block_end]

# Standard XZ stream header:
# 6 bytes magic: \xfd 7z X Z \x00
# 2 bytes flags: raw_block[6:8]
flags = raw_block[6:8]
crc_header = binascii.crc32(flags).to_bytes(4, "little")
print(f"Stream flags: {flags.hex()}, Calculated CRC: {crc_header.hex()}")
print(f"Original bytes 8..11: {raw_block[8:12].hex()}")

# Construct valid standard XZ block
valid_xz = b"\xfd7zXZ\x00" + flags + crc_header + raw_block[12:]

try:
    decomp = lzma.decompress(valid_xz)
    print(f"SUCCESS! Decompressed {len(decomp)} bytes!")
    print(f"First 64 bytes:\n{decomp[:64]}")
except Exception as e:
    print(f"Failed with calculated CRC: {e}")
