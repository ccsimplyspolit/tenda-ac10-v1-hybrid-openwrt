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
    
    # Search for all occurrences of "8367" in strings
    pos = 0
    found_strings = []
    while True:
        idx = data.find(b"8367", pos)
        if idx == -1: break
        # find string start and end
        s_start = data.rfind(b"\x00", 0, idx) + 1
        s_end = data.find(b"\x00", idx)
        s = data[s_start:s_end].decode("latin1", errors="replace")
        va = 0x80000000 + s_start
        found_strings.append((va, s))
        pos = idx + 1

    print(f"Found {len(found_strings)} strings containing 8367:")
    for va, s in found_strings:
        print(f"  0x{va:08x}: {repr(s)}")
        # Find pointers to va
        ptr = struct.pack("<I", va)
        p = 0
        while True:
            pidx = data.find(ptr, p)
            if pidx == -1: break
            pva = 0x80000000 + pidx
            print(f"    Pointer at 0x{pva:08x} ({get_sym(pva, sym_list)})")
            p = pidx + 1

if __name__ == "__main__":
    main()
