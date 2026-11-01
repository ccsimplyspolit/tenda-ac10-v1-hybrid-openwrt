import struct
import sys

KERNEL_BIN = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"

def main():
    with open(KERNEL_BIN, "rb") as f:
        data = f.read()

    print(f"Loaded {len(data)} bytes.")

    # 1. Kallsyms structures
    # We found:
    # kallsyms_addresses starts at 0x4ad124 (31434 symbols)
    # kallsyms_num_syms at 0x4cbc50: 31434 (0x00007aca)
    # kallsyms_markers starts at 0x5283a0 (123 entries)
    # kallsyms_token_table at 0x52858c
    # kallsyms_token_index at 0x528900
    
    num_syms = struct.unpack("<I", data[0x4cbc50:0x4cbc54])[0]
    print(f"kallsyms_num_syms: {num_syms}")

    num_markers = (num_syms + 255) // 256
    markers = [struct.unpack("<I", data[0x5283a0+4*k:0x5283a0+4*k+4])[0] for k in range(num_markers)]
    print(f"First 5 markers: {markers[:5]}")
    print(f"Last 5 markers: {markers[-5:]}")

    token_table_offset = 0x528590
    token_index_offset = 0x528900
    indices = [struct.unpack("<H", data[token_index_offset+2*k:token_index_offset+2*k+2])[0] for k in range(256)]
    
    tokens = []
    for k in range(256):
        pos = token_table_offset + indices[k]
        end = data.find(b"\x00", pos)
        tokens.append(data[pos:end])

    print("First 16 tokens:")
    for i, t in enumerate(tokens[:16]):
        print(f"  token[{i}] = {t}")

    # Now let's determine the exact start of kallsyms_names
    # markers[1] is the byte offset of symbol 256 from kallsyms_names!
    # Let's test candidate starts for kallsyms_names around 0x4cbc54..0x4cbc64
    for cand in range(0x4cbc54, 0x4cbc68):
        # Walk 256 symbols starting at cand
        p = cand
        valid = True
        for _ in range(256):
            if p >= len(data):
                valid = False
                break
            l = data[p]
            p += 1 + l
        if valid and (p - cand) == markers[1]:
            print(f"FOUND EXACT kallsyms_names start at 0x{cand:x}!")
            names_start = cand
            break
    else:
        print("Could not match marker[1] exactly, searching...")
        return

    # Now decode all symbols!
    symbols = []
    p = names_start
    for i in range(num_syms):
        addr = struct.unpack("<I", data[0x4ad124+4*i:0x4ad124+4*i+4])[0]
        l = data[p]
        p += 1
        sym_bytes = bytearray()
        for b in data[p:p+l]:
            sym_bytes.extend(tokens[b])
        p += l
        sym_str = sym_bytes.decode("latin1", errors="replace")
        sym_type = sym_str[0] if len(sym_str) > 0 else "?"
        sym_name = sym_str[1:] if len(sym_str) > 0 else ""
        symbols.append((addr, sym_type, sym_name))

    print(f"Successfully decoded {len(symbols)} symbols!")
    print("\nFirst 15 symbols:")
    for s in symbols[:15]:
        print(f"  0x{s[0]:08x} {s[1]} {s[2]}")

    print("\nLast 15 symbols:")
    for s in symbols[-15:]:
        print(f"  0x{s[0]:08x} {s[1]} {s[2]}")

if __name__ == "__main__":
    main()
