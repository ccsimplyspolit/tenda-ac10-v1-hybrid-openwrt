import lzma

FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    data = f.read()

b0 = data[0x23BC72:0x2472FE]

# Block header was 16 bytes (index 12 to 28)
# Compressed payload is exactly 46675 bytes from index 28:
compressed_payload = b0[28:28 + 46675]
print(f"Compressed payload length: {len(compressed_payload)} bytes")

decomp = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 131072}])

try:
    res = decomp.decompress(compressed_payload)
    print(f"SUCCESS! Decompressed {len(res)} bytes!")
    print(f"Is exactly 131072 bytes? {len(res) == 131072}")
    print(f"Decompressor EOF: {decomp.eof}")
    print(f"First 128 bytes hex:\n{res[:128].hex()}")
    # Let's inspect strings in decompressed block:
    cur = []
    found_s = []
    for b in res:
        if 32 <= b <= 126: cur.append(chr(b))
        else:
            if len(cur) >= 6: found_s.append("".join(cur))
            cur = []
    print(f"Found {len(found_s)} strings in block 0. Sample: {found_s[:10]}")
except Exception as e:
    print(f"Error: {e}")
