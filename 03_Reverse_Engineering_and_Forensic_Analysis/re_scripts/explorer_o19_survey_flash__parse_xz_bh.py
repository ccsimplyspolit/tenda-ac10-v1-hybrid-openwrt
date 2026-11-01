FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    data = f.read()

b0 = data[0x23BC72:0x2472FE]
print("Bytes 0..36:")
for i in range(0, 36, 4):
    print(f"  [{i:2d}..{i+3:2d}]: {b0[i:i+4].hex()}  {' '.join(f'{b:02X}' for b in b0[i:i+4])}")

# Let's inspect Block Header starting at index 12:
bh = b0[12:]
# bh[0]: Block Header Size
bh_size = (bh[0] + 1) * 4
print(f"\nBlock Header Size byte: 0x{bh[0]:02X} -> {bh_size} bytes")
print(f"Block Header total range: index 12 to index {12 + bh_size}")
print(f"Block Header bytes: {bh[:bh_size].hex()}")

# bh[1]: Block Flags
# Bit 0-1: Number of filters (1 to 4) = (flags & 3) + 1
# Bit 6: Compressed Size field present
# Bit 7: Uncompressed Size field present
flags = bh[1]
num_filters = (flags & 3) + 1
has_comp_size = bool(flags & 0x40)
has_uncomp_size = bool(flags & 0x80)
print(f"Block Flags: 0x{flags:02X} -> num_filters={num_filters}, has_comp_size={has_comp_size}, has_uncomp_size={has_uncomp_size}")

# Parse VLI (Variable Length Integer) helper
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

curr = 2
if has_comp_size:
    comp_size, curr = parse_vli(bh, curr)
    print(f"Compressed size: {comp_size}")
if has_uncomp_size:
    uncomp_size, curr = parse_vli(bh, curr)
    print(f"Uncompressed size: {uncomp_size}")

for f_i in range(num_filters):
    f_id, curr = parse_vli(bh, curr)
    prop_size, curr = parse_vli(bh, curr)
    props = bh[curr:curr+prop_size]
    curr += prop_size
    print(f"Filter #{f_i}: ID=0x{f_id:02X}, prop_size={prop_size}, props={props.hex()}")

print(f"Current offset before padding/CRC: {curr} (Header size is {bh_size})")
# The remaining bytes in bh[:bh_size] before the last 4 bytes are padding
padding = bh[curr:bh_size-4]
crc = bh[bh_size-4:bh_size]
print(f"Header Padding: {padding.hex()}")
print(f"Header CRC32: {crc.hex()}")

# Verify CRC32 of Block Header:
import binascii
calc_crc = binascii.crc32(bh[:bh_size-4])
print(f"Calculated Header CRC32: {calc_crc:08X} (LE: {calc_crc.to_bytes(4, 'little').hex()})")
