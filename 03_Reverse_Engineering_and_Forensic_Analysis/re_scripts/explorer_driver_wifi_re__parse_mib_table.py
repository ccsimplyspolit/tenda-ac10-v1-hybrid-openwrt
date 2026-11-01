import sys
import re_tool

base_va = 0x805f96bc
total_entries = 0x20c

mib_entries = []
for i in range(total_entries):
    entry_va = base_va + i * 48
    raw = re_tool.read_bytes(entry_va, 48)
    name = re_tool.read_str(entry_va, 32)
    # let's dissect the 48-byte struct
    # byte 0..31: name
    # byte 32..35: int/fn?
    # byte 36..39: offset in priv?
    # byte 40..43: size / type?
    # byte 44..47: handler / flag?
    f32 = int.from_bytes(raw[32:36], 'little')
    f36 = int.from_bytes(raw[36:40], 'little')
    f40 = int.from_bytes(raw[40:44], 'little')
    f44 = int.from_bytes(raw[44:48], 'little')
    mib_entries.append((i, entry_va, name, f32, f36, f40, f44, raw))

print(f"Total entries: {len(mib_entries)}")
for i, va, name, f32, f36, f40, f44, raw in mib_entries[:20]:
    print(f"[{i:3d}] 0x{va:08x}: {name:24s} 0x{f32:08x} 0x{f36:08x} 0x{f40:08x} 0x{f44:08x}")

print("\n--- Key queries ---")
for q in ['xcap', 'ther', 'power', 'pwr', 'diff', 'rfe', 'pwrlevel']:
    matches = [e for e in mib_entries if q in e[2].lower()]
    print(f"=== Matches for '{q}': {len(matches)} ===")
    for i, va, name, f32, f36, f40, f44, raw in matches:
        sym32 = re_tool.addr2sym.get(f32, '')
        sym44 = re_tool.addr2sym.get(f44, '')
        print(f"  [{i:3d}] 0x{va:08x}: {name:28s} f32=0x{f32:08x}({sym32}) f36=0x{f36:08x} f40=0x{f40:08x} f44=0x{f44:08x}({sym44})")
