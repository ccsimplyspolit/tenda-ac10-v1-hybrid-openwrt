import struct

KERNEL_BIN = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"
SYMBOLS_TXT = r"k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_kernel\vmlinux_symbols.txt"

def load_data():
    with open(KERNEL_BIN, "rb") as f:
        data = f.read()
    sym_list = []
    with open(SYMBOLS_TXT, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(maxsplit=2)
            addr = int(parts[0], 16)
            if addr >= 0x80000000:
                sym_list.append((addr, parts[2]))
    sym_list.sort()
    return data, sym_list

def get_sym(addr, sym_list):
    for a, name in reversed(sym_list):
        if a <= addr:
            return f"{name}+0x{addr-a:x}"
    return "unknown"

def main():
    data, sym_list = load_data()
    # Let's inspect 0x80594c00 to 0x80594c50
    off = 0x80594c00 - 0x80000000
    print("--- Memory at 0x80594c00 - 0x80594c60 ---")
    for i in range(24):
        val = struct.unpack("<I", data[off+4*i:off+4*i+4])[0]
        va = 0x80594c00 + 4*i
        sym = get_sym(va, sym_list)
        s_name = ""
        if 0x80000000 <= val < 0x80700000:
            s_off = val - 0x80000000
            end = data.find(b"\x00", s_off)
            if end != -1 and 1 < (end - s_off) < 50:
                s = data[s_off:end].decode("latin1", errors="replace")
                if s.isprintable(): s_name = f'"{s}"'
        print(f"  0x{va:08x} ({sym:<25}): 0x{val:08x} ({val:10d}) {s_name}")

if __name__ == "__main__":
    main()
