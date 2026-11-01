FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    f.seek(0x20000)
    mtd1_data = f.read(0x10000)

print(f"MTD1 size: {len(mtd1_data)} bytes")

# Save raw mtd1 partition to working directory
with open("mtd1_factory_calibration.bin", "wb") as f_out:
    f_out.write(mtd1_data)
print("Saved mtd1_factory_calibration.bin")

# 1. Header analysis
# First 4 bytes:
magic = mtd1_data[:4]
print(f"Magic bytes (0x0000..0x0003): hex={magic.hex()} | LE uint32=0x{int.from_bytes(magic, 'little'):08X} | BE uint32=0x{int.from_bytes(magic, 'big'):08X}")
# Bytes 4..7:
reserved = mtd1_data[4:8]
print(f"Reserved / Header bytes (0x0004..0x0007): hex={reserved.hex()}")

# 2. Parse all entries
# Entries are separated by '\n' (0x0A) or '\0'
entries = []
cur_start = 8
for i in range(8, len(mtd1_data)):
    if mtd1_data[i] in (0x0A, 0x00):
        if i > cur_start:
            line_bytes = mtd1_data[cur_start:i]
            try:
                line_str = line_bytes.decode("ascii")
                if "=" in line_str:
                    k, v = line_str.split("=", 1)
                    entries.append((cur_start, i, k, v))
                else:
                    entries.append((cur_start, i, line_str, ""))
            except UnicodeDecodeError:
                entries.append((cur_start, i, f"<non-ascii: {line_bytes.hex()}>", ""))
        cur_start = i + 1
        # Check if the rest of the partition is 0xFF or 0x00
        if mtd1_data[i] == 0xFF or (i < len(mtd1_data)-1 and mtd1_data[i+1] == 0xFF):
            # check if remaining bytes are all 0xFF
            if all(b == 0xFF for b in mtd1_data[i+1:]):
                print(f"End of active mtd1 data at offset 0x{i+1:04X} (abs: 0x{0x20000+i+1:06X})")
                break

print(f"\nTotal parsed entries: {len(entries)}")
print(f"{'Rel Offset':<12} {'Abs Offset':<12} {'Length':<8} {'Key':<40} {'Value Preview'}")
print("-" * 100)

wlan0_entries = [] # 5GHz (RTL8822B)
wlan1_entries = [] # 2.4GHz (RTL8197F)
other_entries = []

for start, end, k, v in entries:
    length = end - start
    val_prev = v if len(v) <= 45 else v[:42] + "..."
    print(f"+0x{start:04X}      0x{0x20000+start:06X}   {length:<8} {k:<40} {val_prev}")
    if "WLAN0" in k:
        wlan0_entries.append((start, end, k, v))
    elif "WLAN1" in k:
        wlan1_entries.append((start, end, k, v))
    else:
        other_entries.append((start, end, k, v))

print("\n" + "="*80)
print(f"5 GHz (RTL8822B / WLAN0) ENTRIES ({len(wlan0_entries)}):")
print("="*80)
for start, end, k, v in wlan0_entries:
    print(f"  +0x{start:04X} (0x{0x20000+start:06X}): {k} = {v}")

print("\n" + "="*80)
print(f"2.4 GHz (RTL8197F / WLAN1) ENTRIES ({len(wlan1_entries)}):")
print("="*80)
for start, end, k, v in wlan1_entries:
    print(f"  +0x{start:04X} (0x{0x20000+start:06X}): {k} = {v}")

print("\n" + "="*80)
print(f"SYSTEM & BOARD / ETHERNET ENTRIES ({len(other_entries)}):")
print("="*80)
for start, end, k, v in other_entries:
    print(f"  +0x{start:04X} (0x{0x20000+start:06X}): {k} = {v}")
