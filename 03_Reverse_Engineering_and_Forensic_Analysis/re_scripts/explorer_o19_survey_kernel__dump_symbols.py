import struct
import sys

KERNEL_BIN = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"
SYMBOLS_TXT = r"k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_kernel\vmlinux_symbols.txt"

def load_symbols():
    with open(KERNEL_BIN, "rb") as f:
        data = f.read()

    num_syms = struct.unpack("<I", data[0x4cbc50:0x4cbc54])[0]
    token_table_offset = 0x528590
    token_index_offset = 0x528900
    indices = [struct.unpack("<H", data[token_index_offset+2*k:token_index_offset+2*k+2])[0] for k in range(256)]
    
    tokens = []
    for k in range(256):
        pos = token_table_offset + indices[k]
        end = data.find(b"\x00", pos)
        tokens.append(data[pos:end])

    names_start = 0x4cbc60
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

    return data, symbols

def main():
    data, symbols = load_symbols()
    print(f"Total symbols decoded: {len(symbols)}")

    with open(SYMBOLS_TXT, "w", encoding="utf-8") as f:
        for addr, stype, sname in symbols:
            f.write(f"{addr:08x} {stype} {sname}\n")
    print(f"Saved all symbols to {SYMBOLS_TXT}")

    # Search categories
    queries = {
        "cal_flash": ["cal", "flash", "efuse", "mtd", "prom", "hw_setting", "rf_setting"],
        "rtl8822b": ["8822b", "rtl8822", "8822", "rtl8192cd"],
        "rtl865x_hwnat": ["865", "hwnat", "fastpath", "fwdengine", "asic", "napt", "hw_nat"],
        "rtl8367_switch": ["8367", "smi", "mdio", "switch", "rtk_switch", "rtl8367b"]
    }

    for cat, kws in queries.items():
        print(f"\n=================== Category: {cat} ===================")
        matches = []
        for addr, stype, sname in symbols:
            name_lower = sname.lower()
            if any(kw in name_lower for kw in kws):
                matches.append((addr, stype, sname))
        print(f"Found {len(matches)} matching symbols:")
        for addr, stype, sname in matches[:30]:
            print(f"  0x{addr:08x} {stype} {sname}")
        if len(matches) > 30:
            print(f"  ... and {len(matches)-30} more")

if __name__ == "__main__":
    main()
