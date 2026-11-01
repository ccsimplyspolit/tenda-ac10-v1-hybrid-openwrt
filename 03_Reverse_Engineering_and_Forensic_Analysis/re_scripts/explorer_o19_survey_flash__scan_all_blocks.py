import struct
import lzma

FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    data = f.read()

sq_start = 0x23BC12
sq_end = 0x76BD76

# Parse VLI (Variable Length Integer)
def parse_vli(b, offset):
    res = 0
    shift = 0
    while True:
        byte = b[offset]
        offset += 1
        res |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return res, offset

print(f"Scanning for all Tenda XZ compressed blocks in range 0x{sq_start:06X} to 0x{sq_end:06X}...")
pos = sq_start
blocks = []

while True:
    idx = data.find(b"Tenda\x00", pos)
    if idx == -1 or idx >= sq_end:
        break
    
    # Parse block header
    bh_offset = idx + 12
    bh_size = (data[bh_offset] + 1) * 4
    flags = data[bh_offset + 1]
    has_comp_size = bool(flags & 0x40)
    has_uncomp_size = bool(flags & 0x80)
    
    curr = bh_offset + 2
    comp_size = None
    uncomp_size = None
    if has_comp_size:
        comp_size, curr = parse_vli(data, curr)
    if has_uncomp_size:
        uncomp_size, curr = parse_vli(data, curr)
        
    payload_start = idx + 12 + bh_size
    blocks.append({
        "index": len(blocks),
        "flash_offset": idx,
        "rel_offset": idx - sq_start,
        "bh_size": bh_size,
        "payload_start": payload_start,
        "comp_size": comp_size,
        "uncomp_size": uncomp_size
    })
    
    pos = idx + 12 + bh_size + (comp_size if comp_size else 1)

print(f"Total Tenda XZ blocks found: {len(blocks)}")
print(f"{'Idx':<4} {'Flash Offset':<14} {'Rel Offset':<12} {'Comp Size':<12} {'Uncomp Size':<12}")
print("-" * 60)
for b in blocks[:15]:
    print(f"#{b['index']:<3} 0x{b['flash_offset']:08X}     0x{b['rel_offset']:06X}       {b['comp_size']:<12} {b['uncomp_size']}")

print("...")
for b in blocks[-5:]:
    print(f"#{b['index']:<3} 0x{b['flash_offset']:08X}     0x{b['rel_offset']:06X}       {b['comp_size']:<12} {b['uncomp_size']}")

# Test decompressing sample blocks across the range:
print("\nVerifying decompression of 5 arbitrary blocks:")
for test_idx in [0, 5, 20, 50, len(blocks)-1]:
    b = blocks[test_idx]
    payload = data[b['payload_start'] : b['payload_start'] + b['comp_size']]
    decomp = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 131072}])
    try:
        res = decomp.decompress(payload)
        print(f"  Block #{test_idx} (0x{b['flash_offset']:06X}): comp={b['comp_size']} -> uncomp={len(res)} bytes (matches expected {b['uncomp_size']}: {len(res) == b['uncomp_size']})")
    except Exception as e:
        print(f"  Block #{test_idx} FAILED: {e}")
