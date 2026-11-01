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
    # Search for lui $reg, 0x8059 targeting 0x4c10..0x4c30
    # In MIPS: sw $reg, 0x4c1c($base) where base is 0x80590000
    for i in range(0, len(data)-4, 4):
        w = struct.unpack("<I", data[i:i+4])[0]
        op = w >> 26
        # sw is op 0x2b (43)
        if op == 0x2b:
            simm = struct.unpack("<h", data[i:i+2])[0]
            if 0x4c00 <= simm <= 0x4c40:
                va = 0x80000000 + i
                print(f"Store at 0x{va:08x} ({get_sym(va, sym_list)}): offset=0x{simm:04x}")
                # print nearby instructions
                for k in range(-6, 3):
                    nw = struct.unpack("<I", data[i+k*4:i+k*4+4])[0]
                    print(f"    0x{va+k*4:08x}: {nw:08x}")

if __name__ == "__main__":
    main()
