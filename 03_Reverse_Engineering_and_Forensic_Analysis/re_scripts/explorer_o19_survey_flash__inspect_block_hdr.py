FLASH_PATH = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    data = f.read()

# Block 0: 0x23BC72
# Block 1: 0x2472FE
b0 = data[0x23BC72:0x2472FE]
print(f"Block 0: length = {len(b0)} bytes (0x{len(b0):X})")
print("First 32 bytes:", b0[:32].hex())
print("Bytes 24..56 (start of payload):", b0[24:56].hex())
print("Last 32 bytes of Block 0:", b0[-32:].hex())

# Let's inspect the 24-byte header of Block 0:
hdr = b0[:24]
import struct
print("\n--- Header Structure of Block 0 ---")
print("Magic (0..5):", hdr[:6])
# Next bytes:
u16_6, = struct.unpack(">H", hdr[6:8])
print(f"Bytes 6..7 (BE uint16): 0x{u16_6:04X} ({u16_6})")
u32_8, = struct.unpack(">I", hdr[8:12])
print(f"Bytes 8..11 (BE uint32): 0x{u32_8:08X} ({u32_8})")
u32_12, = struct.unpack(">I", hdr[12:16])
print(f"Bytes 12..15 (BE uint32): 0x{u32_12:08X} ({u32_12})")
u32_16, = struct.unpack(">I", hdr[16:20])
print(f"Bytes 16..19 (BE uint32): 0x{u32_16:08X} ({u32_16})")
u32_20, = struct.unpack(">I", hdr[20:24])
print(f"Bytes 20..23 (BE uint32): 0x{u32_20:08X} ({u32_20})")

# Let's check Little Endian unpacking as well
print("\n--- Little Endian Header Unpack ---")
u16_6_le, = struct.unpack("<H", hdr[6:8])
print(f"Bytes 6..7 (LE uint16): 0x{u16_6_le:04X} ({u16_6_le})")
u32_8_le, = struct.unpack("<I", hdr[8:12])
print(f"Bytes 8..11 (LE uint32): 0x{u32_8_le:08X} ({u32_8_le})")
u32_12_le, = struct.unpack("<I", hdr[12:16])
print(f"Bytes 12..15 (LE uint32): 0x{u32_12_le:08X} ({u32_12_le})")
u32_16_le, = struct.unpack("<I", hdr[16:20])
print(f"Bytes 16..19 (LE uint32): 0x{u32_16_le:08X} ({u32_16_le})")
u32_20_le, = struct.unpack("<I", hdr[20:24])
print(f"Bytes 20..23 (LE uint32): 0x{u32_20_le:08X} ({u32_20_le})")
